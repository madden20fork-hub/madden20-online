// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include "ngs2.h"
#include "ngs2_error.h"
#include "ngs2_impl.h"

#include <atomic>
#include <cstring>
#include <limits>
#include <mutex>
#include <new>
#include <unordered_map>
#include <vector>

#include "common/logging/log.h"
#include "core/libraries/error_codes.h"
#include "core/libraries/kernel/kernel.h"

using namespace Libraries::Kernel;

namespace Libraries::Ngs2 {

namespace {

constexpr u32 RackHandleType = 2;
constexpr u32 VoiceHandleType = 4;
constexpr u32 DefaultMaxVoices = 1;
constexpr u32 MaxHleVoices = 4096;

struct RackState {
    OrbisNgs2Handle systemHandle{};
    u32 rackId{};
    u32 maxVoices{};
    uintptr_t userData{};
    OrbisNgs2ContextBufferInfo bufferInfo{};
    OrbisNgs2BufferFreeHandler freeHandler{};
    std::vector<OrbisNgs2Handle> voiceHandles;
};

struct VoiceState {
    OrbisNgs2Handle rackHandle{};
    u32 voiceIndex{};
    u32 stateFlags{};
};

std::mutex hleStateMutex;
std::unordered_map<OrbisNgs2Handle, RackState> rackStates;
std::unordered_map<OrbisNgs2Handle, VoiceState> voiceStates;
std::unordered_map<OrbisNgs2Handle, uintptr_t> reportStates;
std::atomic<OrbisNgs2Handle> nextReportHandle{0x10008};

u32 GetMaxVoices(const OrbisNgs2RackOption* option) {
    return option ? option->maxVoices : DefaultMaxVoices;
}

size_t GetRackBufferSize(const OrbisNgs2RackOption* option) {
    const u32 maxVoices = GetMaxVoices(option);
    if (maxVoices > MaxHleVoices) {
        return 0;
    }

    constexpr size_t handleSize = sizeof(HandleInternal);
    const size_t handleCount = static_cast<size_t>(maxVoices) + 1;
    if (handleCount > std::numeric_limits<size_t>::max() / handleSize) {
        return 0;
    }
    return handleCount * handleSize;
}

void InitializeHandle(HandleInternal* handle, u32 type, u32 id) {
    new (handle) HandleInternal{};
    handle->selfPtr = handle;
    handle->systemData = nullptr;
    handle->refCount.store(1, std::memory_order_relaxed);
    handle->handleType = type;
    handle->handleID = id;
}

} // namespace

s32 HandleReportInvalid(OrbisNgs2Handle handle, u32 handleType) {
    switch (handleType) {
    case 1:
        LOG_ERROR(Lib_Ngs2, "Invalid system handle {}", handle);
        return ORBIS_NGS2_ERROR_INVALID_SYSTEM_HANDLE;
    case 2:
        LOG_ERROR(Lib_Ngs2, "Invalid rack handle {}", handle);
        return ORBIS_NGS2_ERROR_INVALID_RACK_HANDLE;
    case 4:
        LOG_ERROR(Lib_Ngs2, "Invalid voice handle {}", handle);
        return ORBIS_NGS2_ERROR_INVALID_VOICE_HANDLE;
    case 8:
        LOG_ERROR(Lib_Ngs2, "Invalid report handle {}", handle);
        return ORBIS_NGS2_ERROR_INVALID_REPORT_HANDLE;
    default:
        LOG_ERROR(Lib_Ngs2, "Invalid handle {}", handle);
        return ORBIS_NGS2_ERROR_INVALID_HANDLE;
    }
}

void* MemoryClear(void* buffer, size_t size) {
    return memset(buffer, 0, size);
}

s32 StackBufferClose(StackBuffer* stackBuffer, size_t* outTotalSize) {
    if (outTotalSize) {
        *outTotalSize = stackBuffer->usedSize + stackBuffer->alignment;
    }
    return ORBIS_OK;
}

s32 StackBufferOpen(StackBuffer* stackBuffer, void* bufferStart, size_t bufferSize,
                    void** outBuffer, u8 flags) {
    stackBuffer->top = outBuffer;
    stackBuffer->base = bufferStart;
    stackBuffer->size = (size_t)bufferStart;
    stackBuffer->currentOffset = (size_t)bufferStart;
    stackBuffer->usedSize = 0;
    stackBuffer->totalSize = bufferSize;
    stackBuffer->alignment = 8; // this is a fixed value
    stackBuffer->flags = flags;

    if (outBuffer != NULL) {
        *outBuffer = NULL;
    }

    return ORBIS_OK;
}

s32 SystemCleanup(OrbisNgs2Handle systemHandle, OrbisNgs2ContextBufferInfo* outInfo) {
    if (!systemHandle) {
        return ORBIS_NGS2_ERROR_INVALID_HANDLE;
    }

    // TODO

    return ORBIS_OK;
}

s32 SystemSetupCore(StackBuffer* stackBuffer, const OrbisNgs2SystemOption* option,
                    SystemInternal* outSystem) {
    u32 maxGrainSamples = 512;
    u32 numGrainSamples = 256;
    u32 sampleRate = 48000;

    if (option) {
        sampleRate = option->sampleRate;
        maxGrainSamples = option->maxGrainSamples;
        numGrainSamples = option->numGrainSamples;
    }

    if (maxGrainSamples < 64 || maxGrainSamples > 1024 || (maxGrainSamples & 63) != 0) {
        LOG_ERROR(Lib_Ngs2, "Invalid system option (maxGrainSamples={},x64)", maxGrainSamples);
        return ORBIS_NGS2_ERROR_INVALID_MAX_GRAIN_SAMPLES;
    }

    if (numGrainSamples < 64 || numGrainSamples > 1024 || (numGrainSamples & 63) != 0) {
        LOG_ERROR(Lib_Ngs2, "Invalid system option (numGrainSamples={},x64)", numGrainSamples);
        return ORBIS_NGS2_ERROR_INVALID_NUM_GRAIN_SAMPLES;
    }

    if (sampleRate != 11025 && sampleRate != 12000 && sampleRate != 22050 && sampleRate != 24000 &&
        sampleRate != 44100 && sampleRate != 48000 && sampleRate != 88200 && sampleRate != 96000 &&
        sampleRate != 176400 && sampleRate != 192000) {
        LOG_ERROR(Lib_Ngs2, "Invalid system option(sampleRate={}:44.1/48kHz series)", sampleRate);
        return ORBIS_NGS2_ERROR_INVALID_SAMPLE_RATE;
    }

    if (outSystem) {
        // dummy handle
        outSystem->systemHandle = 1;
    }

    return ORBIS_OK;
}

s32 SystemSetup(const OrbisNgs2SystemOption* option, OrbisNgs2ContextBufferInfo* hostBufferInfo,
                OrbisNgs2BufferFreeHandler hostFree, OrbisNgs2Handle* outHandle) {
    u8 optionFlags = 0;
    StackBuffer stackBuffer;
    SystemInternal setupResult;
    void* systemList = NULL;
    size_t requiredBufferSize = 0;
    u32 result = ORBIS_NGS2_ERROR_INVALID_BUFFER_SIZE;

    if (option) {
        if (option->size != 64) {
            LOG_ERROR(Lib_Ngs2, "Invalid system option size ({})", option->size);
            return ORBIS_NGS2_ERROR_INVALID_OPTION_SIZE;
        }
        optionFlags = option->flags >> 31;
    }

    // Init
    StackBufferOpen(&stackBuffer, NULL, 0, NULL, optionFlags);
    result = SystemSetupCore(&stackBuffer, option, 0);

    if (result < 0) {
        return result;
    }

    StackBufferClose(&stackBuffer, &requiredBufferSize);

    // outHandle unprovided
    if (!outHandle) {
        hostBufferInfo->hostBuffer = NULL;
        hostBufferInfo->hostBufferSize = requiredBufferSize;
        MemoryClear(&hostBufferInfo->reserved, sizeof(hostBufferInfo->reserved));
        return ORBIS_OK;
    }

    if (!hostBufferInfo->hostBuffer) {
        LOG_ERROR(Lib_Ngs2, "Invalid system buffer address ({})", hostBufferInfo->hostBuffer);
        return ORBIS_NGS2_ERROR_INVALID_BUFFER_ADDRESS;
    }

    if (hostBufferInfo->hostBufferSize < requiredBufferSize) {
        LOG_ERROR(Lib_Ngs2, "Invalid system buffer size ({}<{}[byte])",
                  hostBufferInfo->hostBufferSize, requiredBufferSize);
        return ORBIS_NGS2_ERROR_INVALID_BUFFER_SIZE;
    }

    // Setup
    StackBufferOpen(&stackBuffer, hostBufferInfo->hostBuffer, hostBufferInfo->hostBufferSize,
                    &systemList, optionFlags);
    result = SystemSetupCore(&stackBuffer, option, &setupResult);

    if (result < 0) {
        return result;
    }

    StackBufferClose(&stackBuffer, &requiredBufferSize);

    // Copy buffer results
    setupResult.bufferInfo = *hostBufferInfo;
    setupResult.hostFree = hostFree;
    // TODO
    // setupResult.systemList = systemList;

    OrbisNgs2Handle systemHandle = setupResult.systemHandle;
    if (hostBufferInfo->hostBufferSize >= requiredBufferSize) {
        *outHandle = systemHandle;
        return ORBIS_OK;
    }

    SystemCleanup(systemHandle, 0);

    LOG_ERROR(Lib_Ngs2, "Invalid system buffer size ({}<{}[byte])", hostBufferInfo->hostBufferSize,
              requiredBufferSize);
    return ORBIS_NGS2_ERROR_INVALID_BUFFER_SIZE;
}

s32 RackQueryBufferSize(const OrbisNgs2RackOption* option,
                        OrbisNgs2ContextBufferInfo* outBufferInfo) {
    if (!outBufferInfo) {
        return ORBIS_NGS2_ERROR_INVALID_BUFFER_ADDRESS;
    }
    if (option && option->size < sizeof(OrbisNgs2RackOption)) {
        return ORBIS_NGS2_ERROR_INVALID_OPTION_SIZE;
    }

    const size_t requiredBufferSize = GetRackBufferSize(option);
    if (requiredBufferSize == 0) {
        return ORBIS_NGS2_ERROR_INVALID_MAX_VOICES;
    }

    outBufferInfo->hostBuffer = nullptr;
    outBufferInfo->hostBufferSize = requiredBufferSize;
    MemoryClear(outBufferInfo->reserved, sizeof(outBufferInfo->reserved));
    return ORBIS_OK;
}

namespace Hle {

s32 RackCreate(OrbisNgs2Handle systemHandle, u32 rackId, const OrbisNgs2RackOption* option,
               const OrbisNgs2ContextBufferInfo* bufferInfo, OrbisNgs2BufferFreeHandler freeHandler,
               OrbisNgs2Handle* outHandle) {
    if (!systemHandle) {
        return ORBIS_NGS2_ERROR_INVALID_SYSTEM_HANDLE;
    }
    if (!outHandle) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    if (!bufferInfo) {
        return ORBIS_NGS2_ERROR_INVALID_BUFFER_INFO;
    }

    OrbisNgs2ContextBufferInfo queryInfo{};
    const s32 queryResult = RackQueryBufferSize(option, &queryInfo);
    if (queryResult < 0) {
        return queryResult;
    }
    if (!bufferInfo->hostBuffer) {
        return ORBIS_NGS2_ERROR_INVALID_BUFFER_ADDRESS;
    }
    if (reinterpret_cast<uintptr_t>(bufferInfo->hostBuffer) % alignof(HandleInternal) != 0) {
        return ORBIS_NGS2_ERROR_INVALID_BUFFER_ALIGN;
    }
    if (bufferInfo->hostBufferSize < queryInfo.hostBufferSize) {
        return ORBIS_NGS2_ERROR_INVALID_BUFFER_SIZE;
    }

    const u32 maxVoices = GetMaxVoices(option);
    auto* handles = static_cast<HandleInternal*>(bufferInfo->hostBuffer);
    InitializeHandle(&handles[0], RackHandleType, rackId);
    const OrbisNgs2Handle rackHandle = reinterpret_cast<OrbisNgs2Handle>(&handles[0]);

    RackState rackState{};
    rackState.systemHandle = systemHandle;
    rackState.rackId = rackId;
    rackState.maxVoices = maxVoices;
    rackState.userData = bufferInfo->userData;
    rackState.bufferInfo = *bufferInfo;
    rackState.freeHandler = freeHandler;
    rackState.voiceHandles.reserve(maxVoices);

    for (u32 voiceIndex = 0; voiceIndex < maxVoices; ++voiceIndex) {
        HandleInternal* voice = &handles[static_cast<size_t>(voiceIndex) + 1];
        InitializeHandle(voice, VoiceHandleType, voiceIndex);
        rackState.voiceHandles.push_back(reinterpret_cast<OrbisNgs2Handle>(voice));
    }

    {
        std::scoped_lock lock{hleStateMutex};
        if (rackStates.contains(rackHandle)) {
            return ORBIS_NGS2_ERROR_BUFFER_BROKEN;
        }
        for (u32 voiceIndex = 0; voiceIndex < maxVoices; ++voiceIndex) {
            voiceStates.emplace(rackState.voiceHandles[voiceIndex],
                                VoiceState{rackHandle, voiceIndex, 0});
        }
        rackStates.emplace(rackHandle, std::move(rackState));
    }

    *outHandle = rackHandle;
    return ORBIS_OK;
}

s32 RackCreateWithAllocator(OrbisNgs2Handle systemHandle, u32 rackId,
                            const OrbisNgs2RackOption* option,
                            const OrbisNgs2BufferAllocator* allocator, OrbisNgs2Handle* outHandle) {
    if (!systemHandle) {
        return ORBIS_NGS2_ERROR_INVALID_SYSTEM_HANDLE;
    }
    if (!outHandle) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    if (!allocator || !allocator->allocHandler) {
        return ORBIS_NGS2_ERROR_INVALID_BUFFER_ALLOCATOR;
    }

    OrbisNgs2ContextBufferInfo bufferInfo{};
    const s32 queryResult = RackQueryBufferSize(option, &bufferInfo);
    if (queryResult < 0) {
        return queryResult;
    }
    bufferInfo.userData = allocator->userData;

    const s32 allocResult = allocator->allocHandler(&bufferInfo);
    if (allocResult < 0) {
        return allocResult;
    }

    const s32 setupResult =
        RackCreate(systemHandle, rackId, option, &bufferInfo, allocator->freeHandler, outHandle);
    if (setupResult < 0 && allocator->freeHandler && bufferInfo.hostBuffer) {
        allocator->freeHandler(&bufferInfo);
    }
    return setupResult;
}

s32 RackDestroy(OrbisNgs2Handle rackHandle, OrbisNgs2ContextBufferInfo* outBufferInfo) {
    RackState rackState{};
    {
        std::scoped_lock lock{hleStateMutex};
        const auto rackIt = rackStates.find(rackHandle);
        if (rackIt == rackStates.end()) {
            return ORBIS_NGS2_ERROR_INVALID_RACK_HANDLE;
        }
        rackState = std::move(rackIt->second);
        for (const OrbisNgs2Handle voiceHandle : rackState.voiceHandles) {
            voiceStates.erase(voiceHandle);
        }
        rackStates.erase(rackIt);
    }

    if (outBufferInfo) {
        *outBufferInfo = rackState.bufferInfo;
    }
    if (rackState.freeHandler) {
        return rackState.freeHandler(&rackState.bufferInfo);
    }
    return ORBIS_OK;
}

s32 RackGetInfo(OrbisNgs2Handle rackHandle, OrbisNgs2RackInfo* outInfo, size_t infoSize) {
    if (!outInfo) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    if (infoSize < sizeof(OrbisNgs2RackInfo)) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_SIZE;
    }

    std::scoped_lock lock{hleStateMutex};
    const auto rackIt = rackStates.find(rackHandle);
    if (rackIt == rackStates.end()) {
        return ORBIS_NGS2_ERROR_INVALID_RACK_HANDLE;
    }

    std::memset(outInfo, 0, sizeof(OrbisNgs2RackInfo));
    outInfo->rackHandle = rackHandle;
    outInfo->bufferInfo = rackIt->second.bufferInfo;
    outInfo->ownerSystemHandle = rackIt->second.systemHandle;
    outInfo->rackId = rackIt->second.rackId;
    outInfo->maxVoices = rackIt->second.maxVoices;
    return ORBIS_OK;
}

s32 RackGetUserData(OrbisNgs2Handle rackHandle, uintptr_t* outUserData) {
    if (!outUserData) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    std::scoped_lock lock{hleStateMutex};
    const auto rackIt = rackStates.find(rackHandle);
    if (rackIt == rackStates.end()) {
        return ORBIS_NGS2_ERROR_INVALID_RACK_HANDLE;
    }
    *outUserData = rackIt->second.userData;
    return ORBIS_OK;
}

s32 RackGetVoiceHandle(OrbisNgs2Handle rackHandle, u32 voiceIndex, OrbisNgs2Handle* outHandle) {
    if (!outHandle) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    std::scoped_lock lock{hleStateMutex};
    const auto rackIt = rackStates.find(rackHandle);
    if (rackIt == rackStates.end()) {
        return ORBIS_NGS2_ERROR_INVALID_RACK_HANDLE;
    }
    if (voiceIndex >= rackIt->second.voiceHandles.size()) {
        return ORBIS_NGS2_ERROR_INVALID_VOICE_INDEX;
    }
    *outHandle = rackIt->second.voiceHandles[voiceIndex];
    return ORBIS_OK;
}

s32 RackSetUserData(OrbisNgs2Handle rackHandle, uintptr_t userData) {
    std::scoped_lock lock{hleStateMutex};
    const auto rackIt = rackStates.find(rackHandle);
    if (rackIt == rackStates.end()) {
        return ORBIS_NGS2_ERROR_INVALID_RACK_HANDLE;
    }
    rackIt->second.userData = userData;
    return ORBIS_OK;
}

s32 SystemRenderSilent(OrbisNgs2Handle systemHandle, const OrbisNgs2RenderBufferInfo* bufferInfo,
                       u32 numBufferInfo) {
    if (!systemHandle) {
        return ORBIS_NGS2_ERROR_INVALID_SYSTEM_HANDLE;
    }
    if (numBufferInfo > 0 && !bufferInfo) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    for (u32 index = 0; index < numBufferInfo; ++index) {
        if (bufferInfo[index].bufferSize > 0 && !bufferInfo[index].buffer) {
            return ORBIS_NGS2_ERROR_INVALID_BUFFER_ADDRESS;
        }
        if (bufferInfo[index].buffer && bufferInfo[index].bufferSize > 0) {
            std::memset(bufferInfo[index].buffer, 0, bufferInfo[index].bufferSize);
        }
    }
    return ORBIS_OK;
}

s32 VoiceControl(OrbisNgs2Handle voiceHandle, const OrbisNgs2VoiceParamHeader* paramList) {
    if (!paramList) {
        return ORBIS_NGS2_ERROR_INVALID_VOICE_CONTROL_ADDRESS;
    }
    std::scoped_lock lock{hleStateMutex};
    if (!voiceStates.contains(voiceHandle)) {
        return ORBIS_NGS2_ERROR_INVALID_VOICE_HANDLE;
    }
    return ORBIS_OK;
}

s32 VoiceGetOwner(OrbisNgs2Handle voiceHandle, OrbisNgs2Handle* outRackHandle, u32* outVoiceId) {
    if (!outRackHandle || !outVoiceId) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    std::scoped_lock lock{hleStateMutex};
    const auto voiceIt = voiceStates.find(voiceHandle);
    if (voiceIt == voiceStates.end()) {
        return ORBIS_NGS2_ERROR_INVALID_VOICE_HANDLE;
    }
    *outRackHandle = voiceIt->second.rackHandle;
    *outVoiceId = voiceIt->second.voiceIndex;
    return ORBIS_OK;
}

s32 VoiceGetState(OrbisNgs2Handle voiceHandle, OrbisNgs2VoiceState* outState, size_t stateSize) {
    if (!outState) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    if (stateSize < sizeof(OrbisNgs2VoiceState)) {
        return ORBIS_NGS2_ERROR_INVALID_VOICE_STATE_SIZE;
    }
    std::scoped_lock lock{hleStateMutex};
    const auto voiceIt = voiceStates.find(voiceHandle);
    if (voiceIt == voiceStates.end()) {
        return ORBIS_NGS2_ERROR_INVALID_VOICE_HANDLE;
    }
    std::memset(outState, 0, stateSize);
    outState->stateFlags = voiceIt->second.stateFlags;
    return ORBIS_OK;
}

s32 VoiceGetStateFlags(OrbisNgs2Handle voiceHandle, u32* outStateFlags) {
    if (!outStateFlags) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    std::scoped_lock lock{hleStateMutex};
    const auto voiceIt = voiceStates.find(voiceHandle);
    if (voiceIt == voiceStates.end()) {
        return ORBIS_NGS2_ERROR_INVALID_VOICE_HANDLE;
    }
    *outStateFlags = voiceIt->second.stateFlags;
    return ORBIS_OK;
}

s32 ReportRegister(uintptr_t handler, OrbisNgs2Handle* outHandle) {
    if (!handler) {
        return ORBIS_NGS2_ERROR_INVALID_REPORT_HANDLER;
    }
    if (!outHandle) {
        return ORBIS_NGS2_ERROR_INVALID_OUT_ADDRESS;
    }
    const OrbisNgs2Handle reportHandle = nextReportHandle.fetch_add(0x10);
    {
        std::scoped_lock lock{hleStateMutex};
        reportStates.emplace(reportHandle, handler);
    }
    *outHandle = reportHandle;
    return ORBIS_OK;
}

s32 ReportUnregister(OrbisNgs2Handle reportHandle) {
    std::scoped_lock lock{hleStateMutex};
    if (reportStates.erase(reportHandle) == 0) {
        return ORBIS_NGS2_ERROR_INVALID_REPORT_HANDLE;
    }
    return ORBIS_OK;
}

} // namespace Hle

} // namespace Libraries::Ngs2
