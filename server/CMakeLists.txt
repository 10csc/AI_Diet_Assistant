cmake_minimum_required(VERSION 3.10)
project(AIDietAssistant)

set(CMAKE_CXX_STANDARD 11)

# [DEPRECATED] C++ 后端已由 server/run_server.py (Flask) 替代。
# 保留 CMakeLists.txt 用于参考，不再推荐编译 backend.cpp。
#
# Windows 下使用原生 WinSock 编译 C++ 后端
if(WIN32)
    add_executable(backend backend.cpp)
    target_link_libraries(backend ws2_32 winhttp)
    target_compile_definitions(backend PRIVATE _WIN32_PLATFORM)
endif()

# Linux 下建议使用 Python 后端（无需编译 C++）
# 运行方式: python3 server/run_server.py
# 详见 server/run_server.py