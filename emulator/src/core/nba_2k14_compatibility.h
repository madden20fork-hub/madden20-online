// SPDX-FileCopyrightText: Copyright 2024-2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#pragma once

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <string_view>

#ifdef _WIN32
// Same declaration as <windows.h> (HMODULE = HINSTANCE__*), so this widely included header does not pull in windows.h.
// (_get_wpgmptr aborts in a narrow-main program.)
extern "C" __declspec(dllimport) unsigned long __stdcall GetModuleFileNameW(struct HINSTANCE__*, wchar_t*,
                                                                           unsigned long);
#endif

namespace Core::Nba2K14Compatibility {

// Mod root = NBA2K14_MOD_ROOT if set, else the parent of the folder holding the core exe (<root>/core/nba2k14-core.exe).
// Feature flags are empty files in <root>/flags/; dev dumps go under <root>/tools and <root>/eboot_dump.
inline const std::string& ModRoot() {
    static const std::string root = [] {
        if (const char* env = std::getenv("NBA2K14_MOD_ROOT"); env && *env) {
            return std::filesystem::path(env).generic_string();
        }
        std::filesystem::path exe;
#ifdef _WIN32
        wchar_t buf[4096];
        const unsigned long n = GetModuleFileNameW(nullptr, buf, 4096);
        if (n > 0 && n < 4096) {
            exe = std::filesystem::path(std::wstring(buf, n));
        }
#else
        std::error_code ec;
        exe = std::filesystem::read_symlink("/proc/self/exe", ec);
#endif
        return exe.parent_path().parent_path().generic_string();
    }();
    return root;
}

// Absolute path of `rel` (forward slashes) under the mod root.
inline std::string ModPath(std::string_view rel) {
    return ModRoot() + "/" + std::string(rel);
}

// True when the feature flag file <root>/flags/<name> exists.
inline bool Flag(std::string_view name) {
    const std::string p = ModPath("flags/" + std::string(name));
    if (FILE* f = std::fopen(p.c_str(), "rb")) {
        std::fclose(f);
        return true;
    }
    return false;
}

inline bool IsTitle(std::string_view title) noexcept {
    static constexpr std::string_view Expected = "NBA2K14";
    size_t expected_index = 0;

    for (unsigned char character : title) {
        if (character >= 'a' && character <= 'z') {
            character = static_cast<unsigned char>(character - ('a' - 'A'));
        }
        if (!((character >= 'A' && character <= 'Z') ||
              (character >= '0' && character <= '9'))) {
            continue;
        }
        if (expected_index == Expected.size() || character != Expected[expected_index]) {
            return false;
        }
        ++expected_index;
    }

    return expected_index == Expected.size();
}

} // namespace Core::Nba2K14Compatibility
