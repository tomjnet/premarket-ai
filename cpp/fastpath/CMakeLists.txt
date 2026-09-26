# premarket-ai fastpath (C++20): the nanobind module premarket_fastpath
# for python/ai-api (text normalization, URL canonicalization, SHA-256,
# SimHash, band keys, key numbers).
# Build inside Podman: the fastpath-* stages of podman/ai-api/Containerfile.
#   fastpath_core       static library, -fno-exceptions -fno-rtti
#   premarket_fastpath  the Python extension (FASTPATH_BUILD_PYTHON=ON, set
#                       by pyproject.toml); the only target with exceptions
cmake_minimum_required(VERSION 3.28)
project(premarket_fastpath VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
# No C++20 modules here. Scanning would add GCC-only flags (-fmodules-ts,
# -fdeps-format) to compile_commands.json, which clang-tidy rejects.
set(CMAKE_CXX_SCAN_FOR_MODULES OFF)
# Everything, Abseil included, is linked into a shared Python extension.
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(FASTPATH_BUILD_TESTS "Build the GoogleTest unit tests" ON)
option(FASTPATH_BUILD_BENCH "Build the Google Benchmark micro-benchmarks" OFF)
option(FASTPATH_BUILD_PYTHON "Build the premarket_fastpath Python module" OFF)

find_package(OpenSSL 3 REQUIRED COMPONENTS Crypto)

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
FetchContent_MakeAvailable(absl)

# Flags for our own targets only (third-party code keeps its defaults).
set(FASTPATH_WARNINGS -Wall -Wextra -Wpedantic -Werror)
set(FASTPATH_NO_EXCEPTIONS_RTTI -fno-exceptions -fno-rtti)

add_library(fastpath_core STATIC
  src/fastpath/hash.cc
  src/fastpath/text.cc
  src/fastpath/url.cc
)
target_include_directories(fastpath_core PUBLIC src)
target_compile_options(fastpath_core PRIVATE
  ${FASTPATH_WARNINGS} ${FASTPATH_NO_EXCEPTIONS_RTTI})
target_link_libraries(fastpath_core PUBLIC
  absl::inlined_vector
  absl::status
  absl::statusor
  absl::strings
  OpenSSL::Crypto)

if(FASTPATH_BUILD_TESTS)
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

  add_executable(fastpath_tests
    tests/hash_test.cc
    tests/text_test.cc
    tests/url_test.cc
  )
  target_compile_options(fastpath_tests PRIVATE
    ${FASTPATH_WARNINGS} ${FASTPATH_NO_EXCEPTIONS_RTTI})
  target_link_libraries(fastpath_tests PRIVATE fastpath_core GTest::gtest_main)
  include(GoogleTest)
  gtest_discover_tests(fastpath_tests DISCOVERY_TIMEOUT 60)
endif()

if(FASTPATH_BUILD_BENCH)
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

  add_executable(fastpath_bench bench/fastpath_bench.cc)
  target_compile_options(fastpath_bench PRIVATE ${FASTPATH_WARNINGS})
  target_link_libraries(fastpath_bench PRIVATE
    fastpath_core benchmark::benchmark)
endif()

if(FASTPATH_BUILD_PYTHON)
  find_package(Python 3.13 REQUIRED
    COMPONENTS Interpreter Development.Module)
  # scikit-build-core puts the build environment's nanobind on the prefix
  # path; outside it, ask the interpreter where nanobind's CMake files are.
  find_package(nanobind CONFIG QUIET)
  if(NOT nanobind_FOUND)
    execute_process(
      COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
      OUTPUT_STRIP_TRAILING_WHITESPACE
      OUTPUT_VARIABLE nanobind_ROOT
      COMMAND_ERROR_IS_FATAL ANY)
    find_package(nanobind CONFIG REQUIRED)
  endif()

  # The one target built with exceptions: nanobind reports errors to Python
  # by throwing (see src/python/binding.cc).
  nanobind_add_module(premarket_fastpath NB_STATIC src/python/binding.cc)
  # nanobind is third-party code too: its headers are included as SYSTEM.
  set_target_properties(nanobind-static PROPERTIES SYSTEM ON)
  target_compile_options(premarket_fastpath PRIVATE ${FASTPATH_WARNINGS})
  target_link_libraries(premarket_fastpath PRIVATE fastpath_core)
  install(TARGETS premarket_fastpath LIBRARY DESTINATION .)
  install(FILES src/python/premarket_fastpath.pyi DESTINATION .)
endif()
