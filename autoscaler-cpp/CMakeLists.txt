cmake_minimum_required(VERSION 3.16)
project(autoscaler CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find libcurl
find_package(CURL REQUIRED)

# Find nlohmann_json
find_package(nlohmann_json QUIET)

add_executable(autoscaler main.cpp)

target_link_libraries(autoscaler
    CURL::libcurl
)

# Link nlohmann_json if found as package, otherwise use system headers
if(nlohmann_json_FOUND)
    target_link_libraries(autoscaler nlohmann_json::nlohmann_json)
endif()

target_include_directories(autoscaler PRIVATE
    /usr/include/nlohmann
)
