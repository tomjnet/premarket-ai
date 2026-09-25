// Copyright 2026 premarket-ai contributors
// SPDX-License-Identifier: MIT

#include "report/pdf_writer.h"

#include <hpdf.h>

#include <cstddef>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "report/text_layout.h"

namespace premarket {
namespace legacy {
namespace {

// US Letter in PDF points.
const float kPageWidth = 612.0f;
const float kPageHeight = 792.0f;
const float kMargin = 54.0f;
const float kBottom = 60.0f;  // keeps text above the footer
const float kTextWidth = kPageWidth - 2 * kMargin;
const float kLineSpacing = 1.35f;

std::string HexStatus(HPDF_STATUS value) {
  static const char kHex[] = "0123456789ABCDEF";
  std::string out;
  for (int shift = 12; shift >= 0; shift -= 4) {
    out.push_back(kHex[(value >> shift) & 0xF]);
  }
  return "0x" + out;
}

}  // namespace

PdfWriter::PdfWriter(const std::string& footer)
    : doc_(nullptr),
      page_(nullptr),
      regular_(nullptr),
      bold_(nullptr),
      footer_(footer),
      page_count_(0),
      y_(0.0f),
      error_no_(HPDF_OK),
      detail_no_(HPDF_OK) {}

PdfWriter::~PdfWriter() {
  if (doc_ != nullptr) HPDF_Free(doc_);
}

void PdfWriter::ErrorHandler(HPDF_STATUS error_no, HPDF_STATUS detail_no,
                             void* user_data) {
  PdfWriter* writer = static_cast<PdfWriter*>(user_data);
  if (writer->error_no_ == HPDF_OK) {
    writer->error_no_ = error_no;
    writer->detail_no_ = detail_no;
  }
}

Status PdfWriter::Create(const std::string& footer,
                         std::unique_ptr<PdfWriter>* out) {
  std::unique_ptr<PdfWriter> writer(new PdfWriter(footer));
  writer->doc_ = HPDF_New(&PdfWriter::ErrorHandler, writer.get());
  if (writer->doc_ == nullptr) return InternalError("HPDF_New failed");
  HPDF_SetCompressionMode(writer->doc_, HPDF_COMP_ALL);
  HPDF_SetInfoAttr(writer->doc_, HPDF_INFO_CREATOR, "premarket-legacy");
  writer->regular_ = HPDF_GetFont(writer->doc_, "Helvetica", nullptr);
  writer->bold_ = HPDF_GetFont(writer->doc_, "Helvetica-Bold", nullptr);
  Status status = writer->CheckError("load fonts");
  if (!status.ok()) return status;
  status = writer->NewPage();
  if (!status.ok()) return status;
  *out = std::move(writer);
  return OkStatus();
}

Status PdfWriter::CheckError(const char* what) {
  if (error_no_ == HPDF_OK) return OkStatus();
  return InternalError(std::string("libharu error while trying to ") + what +
                       ": error " + HexStatus(error_no_) + ", detail " +
                       HexStatus(detail_no_));
}

float PdfWriter::TextWidth(HPDF_Font font, float size,
                           const std::string& text) const {
  const HPDF_TextWidth width = HPDF_Font_TextWidth(
      font, reinterpret_cast<const HPDF_BYTE*>(text.c_str()),
      static_cast<HPDF_UINT>(text.size()));
  return static_cast<float>(width.width) * size / 1000.0f;
}

Status PdfWriter::NewPage() {
  page_ = HPDF_AddPage(doc_);
  if (page_ == nullptr) return CheckError("add a page");
  HPDF_Page_SetSize(page_, HPDF_PAGE_SIZE_LETTER, HPDF_PAGE_PORTRAIT);
  ++page_count_;
  y_ = kPageHeight - kMargin;

  const std::string footer =
      ToPrintableAscii(footer_) + "   |   Page " + std::to_string(page_count_);
  HPDF_Page_BeginText(page_);
  HPDF_Page_SetFontAndSize(page_, regular_, 7.5f);
  HPDF_Page_SetGrayFill(page_, 0.45f);
  HPDF_Page_TextOut(page_, kMargin, 30.0f, footer.c_str());
  HPDF_Page_EndText(page_);
  return CheckError("start a page");
}

Status PdfWriter::EnsureSpace(float height) {
  if (y_ - height >= kBottom) return OkStatus();
  return NewPage();
}

Status PdfWriter::Write(const std::string& text, const TextStyle& style) {
  const HPDF_Font font = style.bold ? bold_ : regular_;
  const float size = style.size;
  const float line_height = size * kLineSpacing;
  const WidthFunction width = [this, font, size](const std::string& s) {
    return TextWidth(font, size, s);
  };

  const std::vector<std::string> paragraphs =
      SplitParagraphs(ToPrintableAscii(text));
  for (std::size_t p = 0; p < paragraphs.size(); ++p) {
    const std::vector<std::string> lines =
        WrapText(paragraphs[p], kTextWidth, width);
    for (std::size_t i = 0; i < lines.size(); ++i) {
      Status status = EnsureSpace(line_height);
      if (!status.ok()) return status;
      HPDF_Page_BeginText(page_);
      HPDF_Page_SetFontAndSize(page_, font, size);
      HPDF_Page_SetGrayFill(page_, style.gray);
      HPDF_Page_TextOut(page_, kMargin, y_ - size, lines[i].c_str());
      HPDF_Page_EndText(page_);
      y_ -= line_height;
    }
  }
  y_ -= style.space_after;
  return CheckError("write text");
}

Status PdfWriter::Rule() {
  Status status = EnsureSpace(10.0f);
  if (!status.ok()) return status;
  HPDF_Page_SetGrayStroke(page_, 0.75f);
  HPDF_Page_SetLineWidth(page_, 0.5f);
  HPDF_Page_MoveTo(page_, kMargin, y_ - 4.0f);
  HPDF_Page_LineTo(page_, kPageWidth - kMargin, y_ - 4.0f);
  HPDF_Page_Stroke(page_);
  y_ -= 10.0f;
  return CheckError("draw a rule");
}

Status PdfWriter::Save(const std::string& path) {
  const std::string what = "save " + path;
  if (HPDF_SaveToFile(doc_, path.c_str()) != HPDF_OK) {
    const Status status = CheckError(what.c_str());
    return status.ok() ? InternalError("cannot " + what) : status;
  }
  return CheckError(what.c_str());
}

}  // namespace legacy
}  // namespace premarket
