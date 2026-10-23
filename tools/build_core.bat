@echo off
rem Madden 20 core build - its OWN source tree (C:\madden20_online\core_src, branch madden20-core),
rem separate from the 2K14 core tree (C:\madden20_online\core_src).
rem Output: C:\madden20_online\core_src\Build\madden-RelWithDebInfo\shadps4.exe
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set "VULKAN_SDK=C:\VulkanSDK\1.4.363.0"
set "PATH=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\Llvm\x64\bin;%VULKAN_SDK%\Bin;C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja;C:\Program Files\CMake\bin;%PATH%"
set "SRC=C:\madden20_online\core_src"
set "BLD=%SRC%\Build\madden-RelWithDebInfo"
if not exist "%BLD%\CMakeCache.txt" (
  cmake -S "%SRC%" -B "%BLD%" -G Ninja ^
    -DCMAKE_BUILD_TYPE=RelWithDebInfo ^
    -DCMAKE_C_COMPILER=clang-cl -DCMAKE_CXX_COMPILER=clang-cl ^
    -DENABLE_NBA_2K14_COMPATIBILITY=ON -DENABLE_UPDATER=OFF ^
    -DFETCHCONTENT_SOURCE_DIR_ABSL="%SRC%\_deps_src\absl-src" ^
    -DFETCHCONTENT_SOURCE_DIR_FMT="%SRC%\_deps_src\fmt-src" || exit /b 1
)
cmake --build "%BLD%" --target shadps4 --parallel
exit /b %ERRORLEVEL%
