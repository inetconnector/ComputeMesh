cmake_minimum_required(VERSION 3.22.1)

project("computemesh-native")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Architecture-specific SIMD & Hardware Vector optimizations
if(${ANDROID_ABI} STREQUAL "arm64-v8a")
    add_compile_options(-O3 -flto -DARM_NEON -mcpu=generic+dotprod+fp16)
elseif(${ANDROID_ABI} STREQUAL "x86_64")
    add_compile_options(-O3 -flto -mavx2 -mfma)
endif()

add_library(
    computemesh-native
    SHARED
    native-lib.cpp
)

find_library(
    log-lib
    log
)

target_link_libraries(
    computemesh-native
    ${log-lib}
)
