// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "ingest/ingester.h"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "absl/log/log.h"
#include "absl/status/status.h"
#include "absl/status/statusor.h"
#include "absl/strings/str_cat.h"
#include "db/pg_connection.h"
#include "db/repository.h"
#include "ingest/dedup.h"
#include "ingest/feed_client.h"

namespace premarket::ingest {
namespace {

constexpr int64_t kNanosPerMicro = 1000;
constexpr int64_t kNanosPerMilli = int64_t{1000} * 1000;

// Everything a run needs besides the FeedProcessor, allocated at startup.
struct RunBuffers {
  HashIndex seen;
  std::string copy_text;
};

// Everything after the run row exists; any error marks the run FAILED.
absl::Status IngestIntoRun(const Config& config, const std::string& feed_date,
                           int64_t run_id, FeedProcessor* processor,
                           RunBuffers* buffers, Repository* repo) {
  const int64_t start = NowNanos();
  const std::string url = FeedUrlForDate(config.feed_url, feed_date);
  LOG(INFO) << "fetching " << url;
  absl::Status status =
      FetchUrl(url, config.fetch_retries, processor->buffer());
  if (!status.ok()) return status;
  const int64_t fetched = NowNanos();

  absl::StatusOr<std::span<NewsItem>> items = processor->ProcessBuffered();
  if (!items.ok()) return items.status();

  PgResult known;  // the views in `seen` point into it
  status = repo->LoadRecentHashes(feed_date, config.dedup_window_days, &known,
                                  &buffers->seen);
  if (!status.ok()) return status;
  const int64_t dedup_start = NowNanos();
  const int dups = FlagDuplicates(*items, &buffers->seen);
  const int64_t dedup_end = NowNanos();

  status = repo->ReplaceDay(run_id, feed_date, *items, &buffers->copy_text);
  if (!status.ok()) return status;
  const int64_t copied = NowNanos();

  const RunStats stats{
      .rows_received = static_cast<int>(items->size()),
      .rows_inserted = static_cast<int>(items->size()),
      .dups = dups,
      .process_us = processor->ProcessLatencyUs(),
      .wait_us = processor->QueueWaitUs(),
      .fetch_ms = (fetched - start) / kNanosPerMilli,
      .parse_us = processor->parse_us(),
      .dedup_us = (dedup_end - dedup_start) / kNanosPerMicro,
      .copy_ms = (copied - dedup_end) / kNanosPerMilli,
      .total_ms = (NowNanos() - start) / kNanosPerMilli,
  };
  status = repo->FinishRun(run_id, stats);
  if (!status.ok()) return status;

  LOG(INFO) << "run " << run_id << " DONE: " << stats.rows_received
            << " received, " << stats.rows_inserted << " inserted, " << dups
            << " duplicates flagged, p50/p99/p99.9 = " << stats.process_us.p50
            << "/" << stats.process_us.p99 << "/" << stats.process_us.p999
            << " us, queue wait p50/p99/p99.9 = " << stats.wait_us.p50 << "/"
            << stats.wait_us.p99 << "/" << stats.wait_us.p999 << " us, fetch "
            << stats.fetch_ms << " ms, parse " << stats.parse_us << " us, pool "
            << processor->pool_us() << " us, dedup " << stats.dedup_us
            << " us, copy " << stats.copy_ms << " ms, total " << stats.total_ms
            << " ms";
  return absl::OkStatus();
}

}  // namespace

absl::StatusOr<std::unique_ptr<FeedProcessor>> FeedProcessor::Create(
    const ProcessorOptions& options) {
  absl::StatusOr<std::unique_ptr<FeedParser>> parser =
      FeedParser::Create(options.max_feed_bytes, options.max_items);
  if (!parser.ok()) return parser.status();
  const int workers = std::max(1, options.workers);
  std::vector<std::unique_ptr<ContentHasher>> hashers;
  hashers.reserve(static_cast<std::size_t>(workers));
  for (int i = 0; i < workers; ++i) {
    absl::StatusOr<std::unique_ptr<ContentHasher>> hasher =
        ContentHasher::Create();
    if (!hasher.ok()) return hasher.status();
    hashers.push_back(*std::move(hasher));
  }
  return std::unique_ptr<FeedProcessor>(
      new FeedProcessor(options, *std::move(parser), std::move(hashers)));
}

FeedProcessor::FeedProcessor(
    const ProcessorOptions& options, std::unique_ptr<FeedParser> parser,
    std::vector<std::unique_ptr<ContentHasher>> hashers)
    : buffer_(options.max_feed_bytes),
      parser_(std::move(parser)),
      items_(options.max_items),
      merger_(options.max_items),
      pool_(WorkerPoolOptions{
          .workers = static_cast<int>(hashers.size()),
          .queue_capacity = options.queue_capacity,
          .max_tasks = options.max_items,
          .pin_cpus = options.pin_cpus,
      }) {
  scratch_.reserve(hashers.size());
  for (std::unique_ptr<ContentHasher>& hasher : hashers) {
    scratch_.push_back(
        WorkerScratch{.hasher = std::move(hasher),
                      .process_ns = SampleBuffer(items_.size())});
  }
  process_views_.reserve(scratch_.size());
  for (const WorkerScratch& scratch : scratch_) {
    process_views_.push_back(&scratch.process_ns);
  }
}

absl::StatusOr<std::span<NewsItem>> FeedProcessor::ProcessFeed(
    std::string_view feed_json) {
  if (!buffer_.Assign(feed_json)) {
    return absl::ResourceExhaustedError(absl::StrCat(
        "feed of ", feed_json.size(),
        " bytes is larger than INGEST_MAX_FEED_BYTES=", buffer_.capacity()));
  }
  return ProcessBuffered();
}

absl::StatusOr<std::span<NewsItem>> FeedProcessor::ProcessBuffered() {
  for (WorkerScratch& scratch : scratch_) scratch.process_ns.Clear();
  parse_us_ = 0;
  pool_us_ = 0;

  const int64_t start = NowNanos();
  absl::Status status = parser_->Parse(buffer_);
  if (!status.ok()) return status;
  const int64_t parsed = NowNanos();
  parse_us_ = (parsed - start) / kNanosPerMicro;

  const auto count = static_cast<std::uint32_t>(parser_->item_count());
  auto task = [this](std::uint32_t index, int worker) {
    ProcessOne(index, worker);
  };
  pool_.Run(count, task);
  pool_us_ = (NowNanos() - parsed) / kNanosPerMicro;

  const std::span<NewsItem> items(items_.data(), count);
  for (std::size_t i = 0; i < items.size(); ++i) {
    if (items[i].error != ItemError::kNone) {
      const absl::Status error = ItemErrorStatus(items[i]);
      return absl::Status(
          error.code(), absl::StrCat("feed item #", i, ": ", error.message()));
    }
  }
  return items;
}

void FeedProcessor::ProcessOne(std::uint32_t index, int worker) {
  WorkerScratch& scratch = scratch_[static_cast<std::size_t>(worker)];
  NewsItem& item = items_[index];
  const int64_t start = NowNanos();
  if (!parser_->ExtractItem(index, &item)) return;
  if (!scratch.hasher->Hash(item.headline, item.body, item.content_hash)) {
    item.error = ItemError::kHashFailed;
    return;
  }
  scratch.process_ns.Record(NowNanos() - start);
}

LatencySummary FeedProcessor::ProcessLatencyUs() {
  return merger_.Summarize(process_views_, kNanosPerMicro);
}

LatencySummary FeedProcessor::QueueWaitUs() {
  return merger_.Summarize(pool_.wait_samples(), kNanosPerMicro);
}

absl::Status RunIngest(const Config& config, const std::string& feed_date) {
  // Startup: allocate everything the run needs before touching the network.
  absl::StatusOr<std::unique_ptr<FeedProcessor>> processor =
      FeedProcessor::Create(ProcessorOptions{
          .workers = config.workers,
          .queue_capacity = config.queue_capacity,
          .max_items = config.max_items,
          .max_feed_bytes = config.max_feed_bytes,
          .pin_cpus = config.cpu_affinity,
      });
  if (!processor.ok()) return processor.status();
  RunBuffers buffers;
  buffers.seen.reserve(config.max_items *
                       static_cast<std::size_t>(config.dedup_window_days + 1));
  // COPY text is about the size of the JSON plus a little per row.
  buffers.copy_text.reserve(config.max_feed_bytes + config.max_items * 128);

  absl::StatusOr<std::unique_ptr<PgConnection>> conn =
      PgConnection::Connect(config.pg_conninfo);
  if (!conn.ok()) return conn.status();
  absl::Status status = ApplySchemaFile(config.schema_file, conn->get());
  if (!status.ok()) return status;
  Repository repo(conn->get());

  absl::StatusOr<int64_t> run_id = repo.StartRun(feed_date, config.workers);
  if (!run_id.ok()) return run_id.status();
  LOG(INFO) << "ingest run " << *run_id << " started for " << feed_date
            << " with " << (*processor)->workers() << " workers (queue "
            << config.queue_capacity << ", cpu affinity "
            << (config.cpu_affinity ? "on" : "off") << ")";

  status = IngestIntoRun(config, feed_date, *run_id, processor->get(), &buffers,
                         &repo);
  if (!status.ok()) {
    const absl::Status failed = repo.FailRun(*run_id, status.ToString());
    if (!failed.ok()) {
      LOG(ERROR) << "could not mark run FAILED: " << failed.message();
    }
  }
  return status;
}

}  // namespace premarket::ingest
