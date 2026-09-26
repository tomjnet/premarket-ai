# premarket-ai ingest (C++20): the modern low-latency ingester.
# Build inside Podman: podman build -f podman/ingest/Containerfile cpp/ingest
cmake_minimum_required(VERSION 3.28)
project(premarket_ingest VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
# No C++20 modules here; scanning adds GCC-only flags that clang-tidy rejects.
set(CMAKE_CXX_SCAN_FOR_MODULES OFF)

option(PREMARKET_BUILD_TESTS "Build the GoogleTest unit tests" ON)
option(PREMARKET_BUILD_BENCH "Build the Google Benchmark micro-benchmarks" OFF)

find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBPQ REQUIRED IMPORTED_TARGET libpq)
pkg_check_modules(LIBCURL REQUIRED IMPORTED_TARGET libcurl)
pkg_check_modules(LIBCRYPTO REQUIRED IMPORTED_TARGET libcrypto)

# Third-party code is pinned by tag + SHA-256, built with its own flags and
# included as SYSTEM so its headers never trip our -Werror.
include(FetchContent)

set(ABSL_PROPAGATE_CXX_STD ON CACHE BOOL "" FORCE)
set(ABSL_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(ABSL_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
FetchContent_Declare(absl
  URL https://github.com/abseil/abseil-cpp/archive/refs/tags/20250512.1.tar.gz
  URL_HASH SHA256=9b7a064305e9fd94d124ffa6cc358592eb42b5da588fb4e07d09254aa40086db
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  SYSTEM
  EXCLUDE_FROM_ALL)

set(SIMDJSON_EXCEPTIONS OFF CACHE BOOL "" FORCE)
set(SIMDJSON_DEVELOPER_MODE OFF CACHE BOOL "" FORCE)
FetchContent_Declare(simdjson
  URL https://github.com/simdjson/simdjson/archive/refs/tags/v3.13.0.tar.gz
  URL_HASH SHA256=07a1bb3587aac18fd6a10a83fe4ab09f1100ab39f0cb73baea1317826b9f9e0d
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
  SYSTEM
  EXCLUDE_FROM_ALL)

FetchContent_MakeAvailable(absl simdjson)

# Flags for our own targets only (third-party code keeps its defaults).
set(PREMARKET_WARNINGS -Wall -Wextra -Wpedantic -Werror)
set(PREMARKET_NO_EXCEPTIONS_RTTI -fno-exceptions -fno-rtti)

add_library(ingest_core STATIC
  src/common/config.cc
  src/common/latency.cc
  src/db/copy_format.cc
  src/db/pg_connection.cc
  src/db/repository.cc
  src/ingest/content_hash.cc
  src/ingest/dedup.cc
  src/ingest/feed_client.cc
  src/ingest/feed_parser.cc
  src/ingest/ingester.cc
  src/ingest/parity.cc
  src/ingest/worker_pool.cc
)
target_include_directories(ingest_core PUBLIC src)
target_compile_options(ingest_core PRIVATE
  ${PREMARKET_WARNINGS} ${PREMARKET_NO_EXCEPTIONS_RTTI})
target_link_libraries(ingest_core PUBLIC
  absl::flat_hash_map
  absl::log
  absl::status
  absl::statusor
  absl::strings
  simdjson::simdjson
  PkgConfig::LIBPQ PkgConfig::LIBCURL PkgConfig::LIBCRYPTO
  Threads::Threads)

add_executable(premarket-ingest src/main.cc)
target_compile_options(premarket-ingest PRIVATE
  ${PREMARKET_WARNINGS} ${PREMARKET_NO_EXCEPTIONS_RTTI})
target_link_libraries(premarket-ingest PRIVATE
  ingest_core
  absl::flags
  absl::flags_parse
  absl::flags_usage
  absl::log_globals
  absl::log_initialize)
install(TARGETS premarket-ingest RUNTIME DESTINATION bin)

if(PREMARKET_BUILD_TESTS)
  enable_testing()
  set(BUILD_GMOCK OFF CACHE BOOL "" FORCE)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.17.0.tar.gz
    URL_HASH SHA256=65fab701d9829d38cb77c14acdc431d2108bfdbf8979e40eb8ae567edf10b27c
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SYSTEM
    EXCLUDE_FROM_ALL)
  FetchContent_MakeAvailable(googletest)

  add_executable(ingest_tests
    tests/config_test.cc
    tests/content_hash_test.cc
    tests/copy_format_test.cc
    tests/dedup_test.cc
    tests/feed_parser_test.cc
    tests/ingester_test.cc
    tests/latency_test.cc
    tests/mpmc_queue_test.cc
    tests/worker_pool_test.cc
  )
  target_compile_options(ingest_tests PRIVATE ${PREMARKET_WARNINGS})
  target_link_libraries(ingest_tests PRIVATE ingest_core GTest::gtest_main)
  include(GoogleTest)
  # Discover at ctest time: the build never runs a sanitizer binary.
  gtest_discover_tests(ingest_tests DISCOVERY_TIMEOUT 60
                       DISCOVERY_MODE PRE_TEST)
endif()

if(PREMARKET_BUILD_BENCH)
  set(BENCHMARK_ENABLE_TESTING OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_GTEST_TESTS OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_WERROR OFF CACHE BOOL "" FORCE)
  set(BENCHMARK_ENABLE_LIBPFM OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(benchmark
    URL https://github.com/google/benchmark/archive/refs/tags/v1.9.1.tar.gz
    URL_HASH SHA256=32131c08ee31eeff2c8968d7e874f3cb648034377dfc32a4c377fa8796d84981
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SYSTEM
    EXCLUDE_FROM_ALL)
  FetchContent_MakeAvailable(benchmark)

  add_executable(ingest_bench bench/ingest_bench.cc)
  target_compile_options(ingest_bench PRIVATE ${PREMARKET_WARNINGS})
  target_link_libraries(ingest_bench PRIVATE ingest_core benchmark::benchmark)
endif()
