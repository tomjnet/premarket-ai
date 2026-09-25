# premarket-ai legacy (C++11): ingest + PDF report.
# Build inside Podman: podman build -f podman/legacy/Containerfile cpp/legacy
cmake_minimum_required(VERSION 3.28)
project(premarket_legacy VERSION 0.1.0 LANGUAGES CXX)

# Production code is strictly C++11.
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(PREMARKET_BUILD_TESTS "Build the GoogleTest unit tests" ON)
option(PREMARKET_BUILD_BENCH "Build the Google Benchmark micro-benchmarks" OFF)

find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBPQ REQUIRED IMPORTED_TARGET libpq)
pkg_check_modules(LIBCURL REQUIRED IMPORTED_TARGET libcurl)
pkg_check_modules(LIBCRYPTO REQUIRED IMPORTED_TARGET libcrypto)
find_path(RAPIDJSON_INCLUDE_DIR rapidjson/document.h REQUIRED)
find_path(HPDF_INCLUDE_DIR hpdf.h REQUIRED)
find_library(HPDF_LIBRARY NAMES hpdf REQUIRED)

# Flags for our own targets only (third-party code keeps its defaults).
set(PREMARKET_WARNINGS -Wall -Wextra -Wpedantic -Werror)
set(PREMARKET_NO_EXCEPTIONS_RTTI -fno-exceptions -fno-rtti)

add_library(legacy_core STATIC
  src/common/config.cc
  src/common/latency_stats.cc
  src/common/logging.cc
  src/common/status.cc
  src/db/copy_format.cc
  src/db/news_repository.cc
  src/db/pg_connection.cc
  src/ingest/dedup.cc
  src/ingest/feed_client.cc
  src/ingest/feed_parser.cc
  src/ingest/ingester.cc
  src/ingest/normalize.cc
  src/ingest/thread_pool.cc
  src/report/pdf_writer.cc
  src/report/report_generator.cc
  src/report/text_layout.cc
)
target_include_directories(legacy_core PUBLIC src)
target_include_directories(legacy_core SYSTEM PUBLIC
  ${RAPIDJSON_INCLUDE_DIR} ${HPDF_INCLUDE_DIR})
target_compile_options(legacy_core PRIVATE
  ${PREMARKET_WARNINGS} ${PREMARKET_NO_EXCEPTIONS_RTTI})
target_link_libraries(legacy_core PUBLIC
  PkgConfig::LIBPQ PkgConfig::LIBCURL PkgConfig::LIBCRYPTO
  ${HPDF_LIBRARY} Threads::Threads)

add_executable(premarket-legacy src/main.cc)
target_compile_options(premarket-legacy PRIVATE
  ${PREMARKET_WARNINGS} ${PREMARKET_NO_EXCEPTIONS_RTTI})
target_link_libraries(premarket-legacy PRIVATE legacy_core)
install(TARGETS premarket-legacy RUNTIME DESTINATION bin)

include(FetchContent)

if(PREMARKET_BUILD_TESTS)
  enable_testing()
  # 1.12.x is the last GoogleTest release that supports C++11.
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/release-1.12.1.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SYSTEM)
  set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)

  add_executable(legacy_tests
    tests/bounded_queue_test.cc
    tests/config_test.cc
    tests/copy_format_test.cc
    tests/dedup_test.cc
    tests/feed_parser_test.cc
    tests/ingester_test.cc
    tests/latency_stats_test.cc
    tests/normalize_test.cc
    tests/status_test.cc
    tests/text_layout_test.cc
    tests/thread_pool_test.cc
  )
  target_compile_options(legacy_tests PRIVATE ${PREMARKET_WARNINGS})
  target_link_libraries(legacy_tests PRIVATE legacy_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(legacy_tests DISCOVERY_TIMEOUT 60)
endif()

if(PREMARKET_BUILD_BENCH)
  # Google Benchmark needs C++14, so only the benchmark target uses it;
  # the code under test is the same C++11 library.
  set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_WERROR OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_LIBPFM OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(benchmark
    URL https://github.com/google/benchmark/archive/refs/tags/v1.9.1.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SYSTEM)
  FetchContent_MakeAvailable(benchmark)
  set_target_properties(benchmark benchmark_main PROPERTIES CXX_STANDARD 14)

  add_executable(legacy_bench bench/legacy_bench.cc)
  set_target_properties(legacy_bench PROPERTIES CXX_STANDARD 14)
  target_compile_options(legacy_bench PRIVATE ${PREMARKET_WARNINGS})
  target_link_libraries(legacy_bench PRIVATE legacy_core benchmark::benchmark)
endif()
