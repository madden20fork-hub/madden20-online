// SPDX-FileCopyrightText: Copyright 2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <cstdlib>
#include <cstring>

#include <gtest/gtest.h>

#include "core/libraries/error_codes.h"
#include "core/libraries/ngs2/ngs2.h"
#include "core/libraries/ngs2/ngs2_error.h"

namespace Libraries::Ngs2 {
namespace {

struct TestAllocatorContext {
    u32 allocCount{};
    u32 freeCount{};
    uintptr_t observedUserData{};
};

s32 PS4_SYSV_ABI TestRackAlloc(OrbisNgs2ContextBufferInfo* info) {
    auto* context = reinterpret_cast<TestAllocatorContext*>(info->userData);
    context->allocCount++;
    context->observedUserData = info->userData;
    info->hostBuffer = std::malloc(info->hostBufferSize);
    return info->hostBuffer ? ORBIS_OK : ORBIS_NGS2_ERROR_FAIL;
}

s32 PS4_SYSV_ABI TestRackFree(OrbisNgs2ContextBufferInfo* info) {
    auto* context = reinterpret_cast<TestAllocatorContext*>(info->userData);
    context->freeCount++;
    std::free(info->hostBuffer);
    info->hostBuffer = nullptr;
    return ORBIS_OK;
}

TEST(Ngs2Test, RackQueryBufferSizeInitializesSuccessfulOutput) {
    OrbisNgs2ContextBufferInfo info;
    std::memset(&info, 0xA5, sizeof(info));
    const size_t poisoned_size = info.hostBufferSize;
    const uintptr_t poisoned_user_data = info.userData;

    EXPECT_EQ(RackQueryBufferSize(nullptr, &info), ORBIS_OK);
    EXPECT_EQ(info.hostBuffer, nullptr);
    EXPECT_GT(info.hostBufferSize, 0);
    EXPECT_NE(info.hostBufferSize, poisoned_size);
    for (const auto value : info.reserved) {
        EXPECT_EQ(value, 0);
    }
    EXPECT_EQ(info.userData, poisoned_user_data);
}

TEST(Ngs2Test, RackQueryBufferSizeRejectsInvalidArguments) {
    EXPECT_EQ(RackQueryBufferSize(nullptr, nullptr), ORBIS_NGS2_ERROR_INVALID_BUFFER_ADDRESS);

    OrbisNgs2RackOption option{};
    option.size = sizeof(option) - 1;
    OrbisNgs2ContextBufferInfo info{};
    EXPECT_EQ(RackQueryBufferSize(&option, &info), ORBIS_NGS2_ERROR_INVALID_OPTION_SIZE);
}

TEST(Ngs2Test, RackLifecycleProducesStableVoiceHandles) {
    OrbisNgs2RackOption option{};
    option.size = sizeof(option);
    option.maxVoices = 4;

    TestAllocatorContext context{};
    const OrbisNgs2BufferAllocator allocator = {TestRackAlloc, TestRackFree,
                                                reinterpret_cast<uintptr_t>(&context)};

    OrbisNgs2Handle rackHandle = 0;
    ASSERT_EQ(Hle::RackCreateWithAllocator(1, 0x2000, &option, &allocator, &rackHandle), ORBIS_OK);
    ASSERT_NE(rackHandle, 0);
    EXPECT_EQ(context.allocCount, 1);
    EXPECT_EQ(context.observedUserData, reinterpret_cast<uintptr_t>(&context));

    OrbisNgs2Handle voice0 = 0;
    OrbisNgs2Handle voice1 = 0;
    ASSERT_EQ(Hle::RackGetVoiceHandle(rackHandle, 0, &voice0), ORBIS_OK);
    ASSERT_EQ(Hle::RackGetVoiceHandle(rackHandle, 1, &voice1), ORBIS_OK);
    EXPECT_NE(voice0, 0);
    EXPECT_NE(voice1, 0);
    EXPECT_NE(voice0, voice1);
    EXPECT_EQ(Hle::RackGetVoiceHandle(rackHandle, option.maxVoices, &voice1),
              ORBIS_NGS2_ERROR_INVALID_VOICE_INDEX);

    OrbisNgs2Handle owner = 0;
    u32 voiceId = 0xffffffff;
    EXPECT_EQ(Hle::VoiceGetOwner(voice1, &owner, &voiceId), ORBIS_OK);
    EXPECT_EQ(owner, rackHandle);
    EXPECT_EQ(voiceId, 1);

    OrbisNgs2VoiceParamHeader control{};
    control.size = sizeof(control);
    EXPECT_EQ(Hle::VoiceControl(voice0, &control), ORBIS_OK);

    u32 stateFlags = 0xffffffff;
    EXPECT_EQ(Hle::VoiceGetStateFlags(voice0, &stateFlags), ORBIS_OK);
    EXPECT_EQ(stateFlags, 0);

    alignas(OrbisNgs2VoiceState) unsigned char stateStorage[32];
    std::memset(stateStorage, 0xa5, sizeof(stateStorage));
    auto* state = reinterpret_cast<OrbisNgs2VoiceState*>(stateStorage);
    EXPECT_EQ(Hle::VoiceGetState(voice0, state, sizeof(stateStorage)), ORBIS_OK);
    for (const unsigned char value : stateStorage) {
        EXPECT_EQ(value, 0);
    }

    EXPECT_EQ(Hle::RackDestroy(rackHandle, nullptr), ORBIS_OK);
    EXPECT_EQ(context.freeCount, 1);
    EXPECT_EQ(Hle::RackGetVoiceHandle(rackHandle, 0, &voice0),
              ORBIS_NGS2_ERROR_INVALID_RACK_HANDLE);
    EXPECT_EQ(Hle::VoiceGetStateFlags(voice0, &stateFlags), ORBIS_NGS2_ERROR_INVALID_VOICE_HANDLE);
}

TEST(Ngs2Test, SystemRenderWritesDeterministicSilence) {
    unsigned char audio[64];
    std::memset(audio, 0xa5, sizeof(audio));
    const OrbisNgs2RenderBufferInfo bufferInfo = {audio, sizeof(audio), 0, 2};

    EXPECT_EQ(Hle::SystemRenderSilent(1, &bufferInfo, 1), ORBIS_OK);
    for (const unsigned char value : audio) {
        EXPECT_EQ(value, 0);
    }
}

} // namespace
} // namespace Libraries::Ngs2
