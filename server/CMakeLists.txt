cmake_minimum_required(VERSION 3.10)
project(AIDietAssistant)

set(CMAKE_CXX_STANDARD 11)

# 最简化配置 - 只使用Windows系统库
add_executable(backend backend.cpp)

target_link_libraries(backend 
    ws2_32
)