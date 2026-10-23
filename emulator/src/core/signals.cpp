// SPDX-FileCopyrightText: Copyright 2024-2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include "common/arch.h"
#include "common/assert.h"
#include "common/decoder.h"
#include "common/signal_context.h"
#include "core/libraries/kernel/threads/exception.h"
#include "core/signals.h"
#include "emulator.h"

#ifdef _WIN32
#ifdef ENABLE_NBA_2K14_COMPATIBILITY
#include <algorithm>
#include <array>
#include <cstring>
#include <vector>
#endif
#include <windows.h>
static constexpr DWORD MS_VC_EXCEPTION = 0x406D1388;
#else
#include <csignal>
#include <pthread.h>
#ifdef ARCH_X86_64
#include <Zydis/Formatter.h>
#endif
#endif

#ifndef _WIN32
namespace Libraries::Kernel {
void SigactionHandler(int native_signum, siginfo_t* inf, ucontext_t* raw_context);
extern std::array<OrbisKernelExceptionHandler, 32> Handlers;
} // namespace Libraries::Kernel
#endif

namespace Core {

#if defined(_WIN32)

#ifdef ENABLE_NBA_2K14_COMPATIBILITY
template <size_t N>
static bool WriteCompatibilityBytes(uintptr_t address,
                                    const std::array<u8, N>& values) noexcept {
    DWORD old_protect = 0;
    if (!VirtualProtect(reinterpret_cast<void*>(address), values.size(), PAGE_EXECUTE_READWRITE,
                        &old_protect)) {
        return false;
    }

    std::memcpy(reinterpret_cast<void*>(address), values.data(), values.size());
    FlushInstructionCache(GetCurrentProcess(), reinterpret_cast<const void*>(address),
                          values.size());

    DWORD ignored = 0;
    return VirtualProtect(reinterpret_cast<void*>(address), values.size(), old_protect, &ignored) !=
           0;
}

void ApplyNba2K14ComponentRateFallback(
    std::span<const ExecutableMemoryRange> executable_ranges) noexcept {
    // The branch displacement varies between executable revisions. The surrounding provider ID,
    // state member, configured-rate load and output store form the compatibility contract.
    static constexpr std::array<s16, 43> ProviderPattern{
        0x81, 0xfe, 0x9c, 0xdd, 0x49, 0x2d, 0x0f, 0x85, -1,   -1,   -1,
        -1,   0xb8, 0x92, 0xdd, 0x23, 0xc0, 0x48, 0x83, 0xbf, 0x90, 0x00,
        0x00, 0x00, 0x00, 0x0f, 0x84, -1,   -1,   -1,   -1,   0xc5, 0xfa,
        0x10, 0x87, 0x0c, 0x01, 0x00, 0x00, 0xc5, 0xfa, 0x11, 0x02,
    };
    static constexpr size_t StateGateOffset = 25;
    static constexpr std::array<u8, 2> StateGateOpcode{0x0f, 0x84};
    static constexpr std::array<u8, 6> BypassStateGate{0x90, 0x90, 0x90,
                                                       0x90, 0x90, 0x90};
    static constexpr size_t ScanChunkSize = 1 << 20;

    std::vector<uintptr_t> matches;
    std::vector<u8> buffer(ScanChunkSize + ProviderPattern.size() - 1);

    for (const auto& range : executable_ranges) {
        if (range.address == 0 || range.size < ProviderPattern.size()) {
            continue;
        }

        size_t range_offset = 0;
        while (range_offset < range.size && matches.size() < 2) {
            const size_t requested =
                std::min(buffer.size(), static_cast<size_t>(range.size - range_offset));
            SIZE_T bytes_read = 0;
            if (!ReadProcessMemory(GetCurrentProcess(),
                                   reinterpret_cast<const void*>(range.address + range_offset),
                                   buffer.data(), requested, &bytes_read) ||
                bytes_read != requested) {
                LOG_ERROR(Debug,
                          "NBA 2K14 compatibility: could not scan executable memory range "
                          "at {:#x} (size {:#x})",
                          range.address + range_offset, requested);
                break;
            }

            if (bytes_read < ProviderPattern.size()) {
                break;
            }
            const size_t last_start = bytes_read - ProviderPattern.size();
            for (size_t candidate = 0; candidate <= last_start; ++candidate) {
                bool is_match = true;
                for (size_t pattern_index = 0; pattern_index < ProviderPattern.size();
                     ++pattern_index) {
                    const s16 expected = ProviderPattern[pattern_index];
                    if (expected >= 0 && buffer[candidate + pattern_index] != expected) {
                        is_match = false;
                        break;
                    }
                }
                if (is_match) {
                    matches.push_back(range.address + range_offset + candidate);
                    if (matches.size() == 2) {
                        break;
                    }
                }
            }

            if (requested == range.size - range_offset) {
                break;
            }
            range_offset += bytes_read - (ProviderPattern.size() - 1);
        }
        if (matches.size() == 2) {
            break;
        }
    }

    if (matches.empty()) {
        LOG_WARNING(Debug,
                    "NBA 2K14 compatibility: component-rate provider signature was not found; "
                    "continuing without that fallback");
        return;
    }
    if (matches.size() != 1) {
        LOG_ERROR(Debug,
                  "NBA 2K14 compatibility: component-rate provider signature was ambiguous; "
                  "no executable bytes were changed");
        return;
    }

    const uintptr_t state_gate = matches.front() + StateGateOffset;
    std::array<u8, 6> observed_state_gate{};
    SIZE_T state_gate_bytes_read = 0;
    if (!ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(state_gate),
                           observed_state_gate.data(), observed_state_gate.size(),
                           &state_gate_bytes_read) ||
        state_gate_bytes_read != observed_state_gate.size() ||
        !std::equal(StateGateOpcode.begin(), StateGateOpcode.end(),
                    observed_state_gate.begin())) {
        LOG_ERROR(Debug,
                  "NBA 2K14 compatibility: component-rate state gate changed after signature "
                  "matching; no executable bytes were changed");
        return;
    }
    if (!WriteCompatibilityBytes(state_gate, BypassStateGate)) {
        LOG_ERROR(Debug,
                  "NBA 2K14 compatibility: failed to bypass the component-rate state gate "
                  "at {:#x}",
                  state_gate);
        return;
    }

    LOG_WARNING(Debug,
                "NBA 2K14 compatibility: bypassed the component-rate state gate at {:#x}",
                state_gate);
}
#endif

static LONG WINAPI SignalHandler(EXCEPTION_POINTERS* pExp) noexcept {
    const auto* signals = Signals::Instance();
    DWORD code = 0;
    PVOID address = nullptr;

    if (pExp != nullptr && pExp->ExceptionRecord != nullptr) {
        code = pExp->ExceptionRecord->ExceptionCode;
        address = pExp->ExceptionRecord->ExceptionAddress;
    }

    bool handled = false;
    switch (code) {
    case EXCEPTION_ACCESS_VIOLATION:
        handled = signals->DispatchAccessViolation(
            pExp, reinterpret_cast<void*>(pExp->ExceptionRecord->ExceptionInformation[1]));
        break;
    case EXCEPTION_ILLEGAL_INSTRUCTION:
        handled = signals->DispatchIllegalInstruction(pExp);
        break;
    case DBG_PRINTEXCEPTION_C:
    case DBG_PRINTEXCEPTION_WIDE_C:
        // Used by OutputDebugString functions.
        return EXCEPTION_CONTINUE_EXECUTION;
    case MS_VC_EXCEPTION:
        LOG_DEBUG(Debug, "Pass MS_VC_EXCEPTION at {} to handler", address);
        return EXCEPTION_EXECUTE_HANDLER;
    default:
        break;
    }

    if (handled) {
        return EXCEPTION_CONTINUE_EXECUTION;
    }

    // Breakpoints almost certainly come from our asserts/unreachables, no need to log it again.
    if (code != EXCEPTION_BREAKPOINT) {
        LOG_CRITICAL(Debug, "Unhandled Exception code {:#x} at {}", code, address);
        Common::Singleton<Core::Emulator>::Instance()->Shutdown();
    }

    return EXCEPTION_CONTINUE_SEARCH;
}

#else

static std::string DisassembleInstruction(void* code_address) {
    char buffer[256] = "<unable to decode>";

#ifdef ARCH_X86_64
    ZydisDecodedInstruction instruction;
    ZydisDecodedOperand operands[ZYDIS_MAX_OPERAND_COUNT];
    const auto status =
        Common::Decoder::Instance()->decodeInstruction(instruction, operands, code_address);
    if (ZYAN_SUCCESS(status)) {
        ZydisFormatter formatter;
        ZydisFormatterInit(&formatter, ZYDIS_FORMATTER_STYLE_INTEL);
        ZydisFormatterFormatInstruction(&formatter, &instruction, operands,
                                        instruction.operand_count_visible, buffer, sizeof(buffer),
                                        reinterpret_cast<u64>(code_address), ZYAN_NULL);
    }
#endif

    return buffer;
}

void SignalHandler(int sig, siginfo_t* info, void* raw_context) {
    const auto* signals = Signals::Instance();

    auto* code_address = Common::GetRip(raw_context);

    switch (sig) {
    case SIGSEGV:
    case SIGBUS: {
        const bool is_write = Common::IsWriteError(raw_context);
        if (!signals->DispatchAccessViolation(raw_context, info->si_addr)) {
            // If the guest has installed a custom signal handler, and the access violation didn't
            // come from HLE memory tracking, pass the signal on
            if (Libraries::Kernel::Handlers[Libraries::Kernel::NativeToOrbisSignal(sig)]) {
                Libraries::Kernel::SigactionHandler(sig, info,
                                                    reinterpret_cast<ucontext_t*>(raw_context));
                return;
            }
            UNREACHABLE_MSG("Unhandled access violation at code address {}: {} address {}",
                            fmt::ptr(code_address), is_write ? "Write to" : "Read from",
                            fmt::ptr(info->si_addr));
        }
        break;
    }
    case SIGILL:
        if (!signals->DispatchIllegalInstruction(raw_context)) {
            if (Libraries::Kernel::Handlers[Libraries::Kernel::NativeToOrbisSignal(sig)]) {
                Libraries::Kernel::SigactionHandler(sig, info,
                                                    reinterpret_cast<ucontext_t*>(raw_context));
                return;
            }
            UNREACHABLE_MSG("Unhandled illegal instruction at code address {}: {}",
                            fmt::ptr(code_address), DisassembleInstruction(code_address));
        }
        break;
    default:
        if (sig == SIGSLEEP) {
            // Sleep thread until signal is received again
            sigset_t sigset;
            sigemptyset(&sigset);
            sigaddset(&sigset, SIGSLEEP);
            sigwait(&sigset, &sig);
        }
        break;
    }
}

#endif

SignalDispatch::SignalDispatch() {
#if defined(_WIN32)
    ASSERT_MSG(handle = AddVectoredExceptionHandler(0, SignalHandler),
               "Failed to register exception handler.");
#else
    struct sigaction action{};
    action.sa_sigaction = SignalHandler;
    action.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&action.sa_mask);

    ASSERT_MSG(sigaction(SIGSEGV, &action, nullptr) == 0 &&
                   sigaction(SIGBUS, &action, nullptr) == 0,
               "Failed to register access violation signal handler.");
    ASSERT_MSG(sigaction(SIGILL, &action, nullptr) == 0,
               "Failed to register illegal instruction signal handler.");
    ASSERT_MSG(sigaction(SIGSLEEP, &action, nullptr) == 0,
               "Failed to register sleep signal handler.");
#endif
}

SignalDispatch::~SignalDispatch() {
#if defined(_WIN32)
    ASSERT_MSG(RemoveVectoredExceptionHandler(handle), "Failed to remove exception handler.");
#else
    struct sigaction action{};
    action.sa_handler = SIG_DFL;
    action.sa_flags = 0;
    sigemptyset(&action.sa_mask);

    ASSERT_MSG(sigaction(SIGSEGV, &action, nullptr) == 0 &&
                   sigaction(SIGBUS, &action, nullptr) == 0,
               "Failed to remove access violation signal handler.");
    ASSERT_MSG(sigaction(SIGILL, &action, nullptr) == 0,
               "Failed to remove illegal instruction signal handler.");
#endif
}

bool SignalDispatch::DispatchAccessViolation(void* context, void* fault_address) const {
    for (const auto& [handler, _] : access_violation_handlers) {
        if (handler(context, fault_address)) {
            return true;
        }
    }
    return false;
}

bool SignalDispatch::DispatchIllegalInstruction(void* context) const {
    for (const auto& [handler, _] : illegal_instruction_handlers) {
        if (handler(context)) {
            return true;
        }
    }
    return false;
}

} // namespace Core
