cmake_minimum_required(VERSION 3.20)
project(open_vinc_benchmarks VERSION 0.1.0 LANGUAGES C CXX)

# This suite's attribution accompanies the upstream notices deployed below.
# Configure inputs are tracked, so notice edits do not require a binary relink.
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/licenses/open-vinc-benchmarks")
foreach(notice LICENSE NOTICE)
    configure_file("${CMAKE_CURRENT_SOURCE_DIR}/${notice}"
        "${CMAKE_BINARY_DIR}/licenses/open-vinc-benchmarks/${notice}" COPYONLY)
endforeach()

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>DLL")
    add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:/utf-8>")
endif()

find_package(Git REQUIRED)
set(vinc_root "${CMAKE_CURRENT_SOURCE_DIR}/library/open-vinc")
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/cmake/open-vinc-revision.txt" vinc_expected)
string(STRIP "${vinc_expected}" vinc_expected)
execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${vinc_root}" rev-parse HEAD
    OUTPUT_VARIABLE vinc_actual OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
if(NOT vinc_actual STREQUAL vinc_expected)
    message(FATAL_ERROR "Open-VINC revision mismatch. Run git submodule update --init --recursive or explicitly update the pin and metadata together.")
endif()

# Keep upstream unchanged. Only targets needed by the native test are built.
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(VINC_BUILD_APPS OFF CACHE BOOL "" FORCE)
set(VINC_BUILD_UI OFF CACHE BOOL "" FORCE)
set(VINC_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(VINC_BUILD_PYTHON OFF CACHE BOOL "" FORCE)
set(VINC_BUILD_BUS_BENCHMARK OFF CACHE BOOL "" FORCE)
set(VINC_NAME "open-vinc-benchmarks" CACHE STRING "Benchmark central identity")
add_subdirectory(library/open-vinc/src open-vinc EXCLUDE_FROM_ALL)

add_message_dir("${CMAKE_CURRENT_SOURCE_DIR}/native/messages")
add_module(vinc_benchmark_module
    MODULE_TYPE_NAME busBenchmark
    SOURCES native/module.cpp)
target_include_directories(vinc_benchmark_module PRIVATE native/include)

add_executable(vinc_benchmark native/driver.cpp)
target_include_directories(vinc_benchmark PRIVATE native/include)
target_link_libraries(vinc_benchmark PRIVATE vinc::module_manager vinc::errors)
add_dependencies(vinc_benchmark vinc_benchmark_module)
vinc_deploy_licenses(vinc_benchmark)
if(WIN32)
    target_link_libraries(vinc_benchmark_module PRIVATE psapi)
    target_link_libraries(vinc_benchmark PRIVATE psapi)
endif()
foreach(target vinc_benchmark vinc_benchmark_module)
    if(MSVC)
        target_compile_options(${target} PRIVATE /W4 /utf-8)
    else()
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endforeach()

# Provenance belongs to the build, rather than guesses based on executable names.
file(GENERATE OUTPUT "${CMAKE_BINARY_DIR}/benchmark-build-$<CONFIG>.json" CONTENT
"{\n  \"schema_version\": 1,\n  \"framework_revision\": \"${vinc_actual}\",\n  \"configuration\": \"$<CONFIG>\",\n  \"compiler\": \"${CMAKE_CXX_COMPILER_ID}\",\n  \"compiler_version\": \"${CMAKE_CXX_COMPILER_VERSION}\",\n  \"cmake_version\": \"${CMAKE_VERSION}\",\n  \"system\": \"${CMAKE_SYSTEM_NAME}\",\n  \"processor\": \"${CMAKE_SYSTEM_PROCESSOR}\",\n  \"executable\": \"$<TARGET_FILE:vinc_benchmark>\",\n  \"plugin\": \"$<TARGET_FILE:vinc_benchmark_module>\",\n  \"host\": \"$<TARGET_FILE:vinc_module_host>\"\n}\n")

option(BENCHMARK_BUILD_TESTS "Enable this repository's validation tests" ON)
if(BENCHMARK_BUILD_TESTS)
    enable_testing()
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    add_test(NAME benchmarks.analysis COMMAND "${Python3_EXECUTABLE}" -m unittest discover -s tests -v)
    set_tests_properties(benchmarks.analysis PROPERTIES WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" TIMEOUT 30)
    add_test(NAME benchmarks.native_smoke
        COMMAND "${Python3_EXECUTABLE}" -m tools.run
            --build-info "${CMAKE_BINARY_DIR}/benchmark-build-$<CONFIG>.json"
            --sizes-bytes 1024 --modes push loan --samples 32 --warmup 64 --repeats 1
            --output "${CMAKE_BINARY_DIR}/smoke-results")
    set_tests_properties(benchmarks.native_smoke PROPERTIES WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" TIMEOUT 90 RUN_SERIAL TRUE)
    if(WIN32)
        add_test(NAME benchmarks.highres_smoke
            COMMAND "${Python3_EXECUTABLE}" -m tools.run
                --build-info "${CMAKE_BINARY_DIR}/benchmark-build-$<CONFIG>.json"
                --sizes-bytes 1024 --modes push loan --samples 32 --warmup 64 --repeats 1
                --pacing windows-highres --output "${CMAKE_BINARY_DIR}/highres-smoke-results")
        set_tests_properties(benchmarks.highres_smoke PROPERTIES WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" TIMEOUT 90 RUN_SERIAL TRUE)
    endif()
endif()
