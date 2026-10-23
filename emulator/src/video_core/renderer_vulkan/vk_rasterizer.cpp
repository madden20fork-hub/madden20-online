// SPDX-FileCopyrightText: Copyright 2024-2026 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <atomic>
#include <cstdio>
#include <filesystem>
#include <cstring>
#include <map>
#include <mutex>
#include <set>
#include <tuple>
#include <unordered_set>
#include "core/nba_2k14_compatibility.h"
#include "common/debug.h"
#include "core/emulator_settings.h"
#include "core/memory.h"
#include "shader_recompiler/runtime_info.h"
#include "video_core/amdgpu/liverpool.h"
#include "video_core/renderer_vulkan/liverpool_to_vk.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/renderer_vulkan/vk_rasterizer.h"
#include "video_core/renderer_vulkan/vk_scheduler.h"
#include "video_core/renderer_vulkan/vk_shader_hle.h"
#include "video_core/texture_cache/image_view.h"
#include "video_core/texture_cache/texture_cache.h"

#ifdef MemoryBarrier
#undef MemoryBarrier
#endif

namespace VideoCore {
extern std::atomic<u64> g_flip_counter;
}

namespace Vulkan {

static Shader::PushData MakeUserData(const AmdGpu::Regs& regs) {
    // TODO(roamic): Add support for multiple viewports and geometry shaders when ViewportIndex
    // is encountered and implemented in the recompiler.
    Shader::PushData push_data{};
    push_data.xoffset = regs.viewport_control.xoffset_enable ? regs.viewports[0].xoffset : 0.f;
    push_data.xscale = regs.viewport_control.xscale_enable ? regs.viewports[0].xscale : 1.f;
    push_data.yoffset = regs.viewport_control.yoffset_enable ? regs.viewports[0].yoffset : 0.f;
    push_data.yscale = regs.viewport_control.yscale_enable ? regs.viewports[0].yscale : 1.f;
    return push_data;
}

Rasterizer::Rasterizer(const Instance& instance_, Scheduler& scheduler_,
                       AmdGpu::Liverpool* liverpool_)
    : instance{instance_}, scheduler{scheduler_}, page_manager{this},
      buffer_cache{instance, scheduler, liverpool_, texture_cache, page_manager},
      texture_cache{instance, scheduler, liverpool_, buffer_cache, page_manager},
      liverpool{liverpool_}, memory{Core::Memory::Instance()},
      pipeline_cache{instance, scheduler, liverpool} {
    if (!EmulatorSettings.IsNullGPU()) {
        liverpool->BindRasterizer(this);
    }
    memory->SetRasterizer(this);
}

Rasterizer::~Rasterizer() = default;

void Rasterizer::CpSync() {
    scheduler.EndRendering();
    auto cmdbuf = scheduler.CommandBuffer();

    const vk::MemoryBarrier ib_barrier{
        .srcAccessMask = vk::AccessFlagBits::eShaderWrite,
        .dstAccessMask = vk::AccessFlagBits::eIndirectCommandRead,
    };
    cmdbuf.pipelineBarrier(vk::PipelineStageFlagBits::eComputeShader,
                           vk::PipelineStageFlagBits::eDrawIndirect,
                           vk::DependencyFlagBits::eByRegion, ib_barrier, {}, {});
}

bool Rasterizer::FilterDraw() {
    const auto& regs = liverpool->regs;
    if (regs.color_control.mode == AmdGpu::ColorControl::OperationMode::EliminateFastClear) {
        // Clears the render target if FCE is launched before any draws
        EliminateFastClear();
        return false;
    }
    if (regs.color_control.mode == AmdGpu::ColorControl::OperationMode::FmaskDecompress) {
        // TODO: check for a valid MRT1 to promote the draw to the resolve pass.
        LOG_TRACE(Render_Vulkan, "FMask decompression pass skipped");
        ScopedMarkerInsert("FmaskDecompress");
        return false;
    }
    if (regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Resolve) {
        LOG_TRACE(Render_Vulkan, "Resolve pass");
        Resolve();
        return false;
    }
    if (regs.primitive_type == AmdGpu::PrimitiveType::None) {
        LOG_TRACE(Render_Vulkan, "Primitive type 'None' skipped");
        ScopedMarkerInsert("PrimitiveTypeNone");
        return false;
    }

    const bool cb_disabled =
        regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Disable;
    const auto depth_copy =
        regs.depth_render_override.force_z_dirty && regs.depth_render_override.force_z_valid &&
        regs.depth_buffer.DepthValid() && regs.depth_buffer.DepthWriteValid() &&
        regs.depth_buffer.DepthAddress() != regs.depth_buffer.DepthWriteAddress();
    const auto stencil_copy =
        regs.depth_render_override.force_stencil_dirty &&
        regs.depth_render_override.force_stencil_valid && regs.depth_buffer.StencilValid() &&
        regs.depth_buffer.StencilWriteValid() &&
        regs.depth_buffer.StencilAddress() != regs.depth_buffer.StencilWriteAddress();
    if (cb_disabled && (depth_copy || stencil_copy)) {
        // Games may disable color buffer and enable force depth/stencil dirty and valid to
        // do a copy from one depth-stencil surface to another, without a pixel shader.
        // We need to detect this case and perform the copy, otherwise it will have no effect.
        LOG_TRACE(Render_Vulkan, "Performing depth-stencil override copy");
        DepthStencilCopy(depth_copy, stencil_copy);
        return false;
    }

    return true;
}

void Rasterizer::PrepareRenderState(const GraphicsPipeline* pipeline) {
    // Prefetch render targets to handle overlaps with bound textures (e.g. mipgen)
    const auto& key = pipeline->GetGraphicsKey();
    const auto& regs = liverpool->regs;
    if (regs.color_control.degamma_enable) {
        LOG_WARNING(Render_Vulkan, "Color buffers require gamma correction");
    }

    const bool skip_cb_binding =
        regs.color_control.mode == AmdGpu::ColorControl::OperationMode::Disable;
    for (s32 cb = 0; cb < std::bit_width(key.mrt_mask); ++cb) {
        auto& [image_id, desc] = cb_descs[cb];
        const auto& col_buf = regs.color_buffers[cb];
        const u32 target_mask = regs.color_target_mask.GetMask(cb);
        if (skip_cb_binding || !col_buf || !target_mask || (key.mrt_mask & (1 << cb)) == 0) {
            image_id = {};
            continue;
        }
        const auto& hint = liverpool->last_cb_extent[cb];
        std::construct_at(&desc, col_buf, hint);
        image_id = bound_images.emplace_back(texture_cache.FindImage(desc));
        auto& image = texture_cache.GetImage(image_id);
        image.binding.is_target = 1u;
    }

    if ((regs.depth_control.depth_enable && regs.depth_buffer.DepthValid()) ||
        (regs.depth_control.stencil_enable && regs.depth_buffer.StencilValid())) {
        const auto htile_address = regs.depth_htile_data_base.GetAddress();
        const auto& hint = liverpool->last_db_extent;
        auto& [image_id, desc] = db_desc;
        std::construct_at(&desc, regs.depth_buffer, regs.depth_view, regs.depth_control,
                          htile_address, hint);
        image_id = bound_images.emplace_back(texture_cache.FindImage(desc));
        auto& image = texture_cache.GetImage(image_id);
        image.binding.is_target = 1u;
    } else {
        db_desc.first = {};
    }
}

static std::pair<u32, u32> GetDrawOffsets(
    const AmdGpu::Regs& regs, const Shader::Info& info,
    const std::optional<Shader::Gcn::FetchShaderData>& fetch_shader) {
    u32 vertex_offset = regs.index_offset;
    u32 instance_offset = 0;
    if (fetch_shader) {
        if (vertex_offset == 0 && fetch_shader->vertex_offset_sgpr != -1) {
            vertex_offset = info.user_data[fetch_shader->vertex_offset_sgpr];
        }
        if (fetch_shader->instance_offset_sgpr != -1) {
            instance_offset = info.user_data[fetch_shader->instance_offset_sgpr];
        }
    }
    return {vertex_offset, instance_offset};
}

void Rasterizer::EliminateFastClear() {
    auto& col_buf = liverpool->regs.color_buffers[0];
    if (!col_buf || !col_buf.info.fast_clear) {
        return;
    }
    VideoCore::TextureCache::ImageDesc desc(col_buf, liverpool->last_cb_extent[0]);
    const auto image_id = texture_cache.FindImage(desc);
    const auto& image_view = texture_cache.FindRenderTarget(image_id, desc);
    if (!texture_cache.IsMetaCleared(col_buf.CmaskAddress(), col_buf.view.slice_start)) {
        return;
    }
    for (u32 slice = col_buf.view.slice_start; slice <= col_buf.view.slice_max; ++slice) {
        texture_cache.TouchMeta(col_buf.CmaskAddress(), slice, false);
    }
    auto& image = texture_cache.GetImage(image_id);
    const auto clear_value = LiverpoolToVK::ColorBufferClearValue(col_buf);

    ScopeMarkerBegin(fmt::format("EliminateFastClear:MRT={:#x}:M={:#x}", col_buf.Address(),
                                 col_buf.CmaskAddress()));
    image.Clear(clear_value, desc.view_info.range);
    ScopeMarkerEnd();
}

// Draw accounting read by the VideoOut flip log (MADDENGFX probe): calls / filtered / no pipeline /
// bind failed / issued, plus dispatches.
std::atomic<u64> g_draw_stats[6]{};
// MADDENGFX: guest address of the present pass's UI coverage mask (the 0x3f48-byte binding).
std::atomic<u64> g_mask_addr{0};

// Madden 20 field-render hunt (flags/MADDENDRAWPROBE), all on the GPU command-processor thread:
//  * flags/DRAWLIST present -> the next 3 flips' draws, dispatches and CP events are written to
//    framedump/drawlistNN.txt, then the trigger is deleted (re-armable without relaunching).
//  * flags/drawskip.txt (hex shader hashes, one per line; re-read whenever it changes) -> draws whose
//    VS or PS hash is listed are skipped, so the culprit draw can be bisected live.
namespace MaddenProbe {
void ReloadWatch();
static std::FILE* out = nullptr;
static u64 rec_start = 0, last_flip = ~0ull, seq = 0;
static u32 list_no = 0;
static std::set<u64> skip;
static std::filesystem::file_time_type skip_mtime{};

bool Enabled() {
    static const bool en = Core::Nba2K14Compatibility::Flag("MADDENDRAWPROBE");
    return en;
}

void Tick() {
    if (!Enabled()) {
        return;
    }
    const u64 flip = VideoCore::g_flip_counter.load();
    if (flip == last_flip) {
        return;
    }
    last_flip = flip;
    ReloadWatch();
    std::error_code ec;
    const auto skip_path = Core::Nba2K14Compatibility::ModPath("flags/drawskip.txt");
    const auto mt = std::filesystem::last_write_time(skip_path, ec);
    if (ec) {
        if (!skip.empty()) {
            skip.clear();
            LOG_WARNING(Render_Vulkan, "MADDENDRAWPROBE skip list cleared");
        }
    } else if (mt != skip_mtime) {
        skip_mtime = mt;
        skip.clear();
        if (std::FILE* f = std::fopen(skip_path.c_str(), "rb")) {
            char line[256];
            while (std::fgets(line, sizeof(line), f)) {
                if (line[0] == '#') {
                    continue;
                }
                const u64 h = std::strtoull(line, nullptr, 16);
                if (h) {
                    skip.insert(h);
                }
            }
            std::fclose(f);
        }
        LOG_WARNING(Render_Vulkan, "MADDENDRAWPROBE skip list: {} hashes", skip.size());
    }
    if (out) {
        std::fprintf(out, "=== FLIP %llu\n", static_cast<unsigned long long>(flip));
        if (flip >= rec_start + 3) {
            std::fclose(out);
            out = nullptr;
            std::filesystem::remove(Core::Nba2K14Compatibility::ModPath("flags/DRAWLIST"), ec);
            LOG_WARNING(Render_Vulkan, "MADDENDRAWPROBE drawlist {} complete ({} lines)", list_no,
                        seq);
            ++list_no;
        }
    } else if (std::filesystem::exists(Core::Nba2K14Compatibility::ModPath("flags/DRAWLIST"))) {
        const auto dir = std::filesystem::path(Core::Nba2K14Compatibility::ModPath("framedump"));
        std::filesystem::create_directories(dir, ec);
        const auto name = dir / fmt::format("drawlist{:02}.txt", list_no);
        out = std::fopen(name.string().c_str(), "wb");
        rec_start = flip;
        seq = 0;
        if (out) {
            std::fprintf(out, "=== FLIP %llu (start)\n", static_cast<unsigned long long>(flip));
        }
    }
}

bool Recording() {
    return out != nullptr;
}

void Line(const std::string& s) {
    if (out) {
        std::fprintf(out, "%llu %s\n", static_cast<unsigned long long>(seq++), s.c_str());
    }
}

bool Skipped(const Pipeline* pipeline) {
    if (skip.empty()) {
        return false;
    }
    for (const auto* st : pipeline->GetStages()) {
        if (st && skip.contains(st->pgm_hash)) {
            return true;
        }
    }
    return false;
}

const char* Mod(VideoCore::BufferCache& bc, VAddr addr, u64 size) {
    if (addr == 0 || size == 0) {
        return "-";
    }
    const bool g = bc.IsRegionGpuModified(addr, size);
    const bool c = bc.IsRegionCpuModified(addr, size);
    return g ? (c ? "GC" : "G") : (c ? "C" : "_");
}

std::string StageDesc(const Shader::Info& st, VideoCore::BufferCache& bc) {
    std::string s = fmt::format(" | {}:{:08x}", static_cast<u32>(st.stage), st.pgm_hash);
    for (const auto& d : st.buffers) {
        if (d.IsSpecial()) {
            continue;
        }
        const auto v = d.GetSharp(st);
        if (v.base_address == 0) {
            continue;
        }
        s += fmt::format(" B{}[{:x}+{:x} s{} {}]", d.is_written ? "w" : "", v.base_address,
                         v.GetSize(), v.stride, Mod(bc, v.base_address, v.GetSize()));
    }
    u32 ti = 0;
    for (const auto& d : st.images) {
        if (ti++ >= 16) {
            break;
        }
        const auto t = d.GetSharp(st);
        s += fmt::format(" T{}[{:x} {}x{} f{} lv{}-{} tm{} p{}]", d.is_written ? "w" : "",
                         t.Address(), t.width + 1, t.height + 1, static_cast<u32>(t.GetDataFmt()),
                         static_cast<u32>(t.base_level), static_cast<u32>(t.last_level),
                         static_cast<u32>(t.tiling_index), static_cast<u32>(t.pitch + 1));
    }
    s += " U:";
    for (u32 i = 0; i < std::min<size_t>(st.user_data.size(), 16); ++i) {
        s += fmt::format("{:x},", st.user_data[i]);
    }
    return s;
}

void DrawLine(const char* kind, const AmdGpu::Regs& regs, const GraphicsPipeline* pipeline,
              VideoCore::BufferCache& bc, const std::string& extra) {
    const auto& cb0 = regs.color_buffers[0];
    std::string s = fmt::format(
        "{} ni={} inst={} ib={:x} rt0={:x} f{} mask={:x} db={:x} z{}{}{} {}", kind,
        regs.num_indices, regs.num_instances.NumInstances(),
        regs.index_base_address.Address<VAddr>(), cb0.Address(),
        static_cast<u32>(cb0.GetDataFmt()), regs.color_target_mask.raw,
        regs.depth_buffer.DepthAddress(), regs.depth_control.depth_enable ? "E" : "-",
        regs.depth_control.depth_write_enable ? "W" : "-",
        static_cast<u32>(regs.depth_control.depth_func), extra);
    s += fmt::format(" vp={:.0f}x{:.0f}", 2.f * std::abs(regs.viewports[0].xscale),
                     2.f * std::abs(regs.viewports[0].yscale));
    Vulkan::VertexInputs<vk::VertexInputAttributeDescription2EXT> attributes;
    Vulkan::VertexInputs<vk::VertexInputBindingDescription2EXT> bindings;
    Vulkan::VertexInputs<vk::VertexInputBindingDivisorDescriptionEXT> divisors;
    Vulkan::VertexInputs<AmdGpu::Buffer> guest_buffers;
    pipeline->GetVertexInputs(attributes, bindings, divisors, guest_buffers,
                              regs.vgt_instance_step_rate_0, regs.vgt_instance_step_rate_1);
    for (const auto& b : guest_buffers) {
        s += fmt::format(" VB[{:x}+{:x} s{} {}]", b.base_address, b.GetSize(), b.GetStride(),
                         Mod(bc, b.base_address, b.GetSize()));
    }
    for (const auto* st : pipeline->GetStages()) {
        if (st) {
            s += StageDesc(*st, bc);
        }
    }
    Line(s);
}
// Read back what the GPU will actually read for each cached (non-stream) buffer of a recorded draw
// and diff it against guest memory. Call only right after BindResources (no render pass/bindings
// recorded yet): it ends rendering and waits for the GPU.
void CompareBuffers(const Pipeline* pipeline, VideoCore::BufferCache& bc, Scheduler& scheduler) {
    std::string s = "  CMP";
    for (const auto* st : pipeline->GetStages()) {
        if (!st) {
            continue;
        }
        for (const auto& d : st->buffers) {
            if (d.IsSpecial() || d.is_written) {
                continue;
            }
            const auto v = d.GetSharp(*st);
            const u64 size = std::min<u64>(v.GetSize(), 8_MB);
            if (v.base_address == 0 || size == 0) {
                continue;
            }
            const bool gpu = bc.IsRegionGpuModified(v.base_address, size);
            if (!gpu && size <= 64_KB) {
                continue; // served by a fresh stream copy of guest memory
            }
            const auto id = bc.FindBuffer(v.base_address, static_cast<u32>(size));
            auto& buf = bc.GetBuffer(id);
            if (!buf.IsInBounds(v.base_address, size)) {
                continue;
            }
            auto& dl = bc.GetUtilityBuffer(VideoCore::MemoryUsage::Download);
            const auto [ptr, off] = dl.Map(size);
            dl.Commit();
            scheduler.EndRendering();
            const vk::BufferCopy copy{buf.Offset(v.base_address), off, size};
            scheduler.CommandBuffer().copyBuffer(buf.Handle(), dl.Handle(), copy);
            scheduler.Finish();
            const u8* guest = reinterpret_cast<const u8*>(v.base_address);
            // Per 4 KiB guest page: differing pages that the CPU has dirtied since the sync are a
            // benign race (game thread running ahead); the rest are stale GPU-side copies.
            u64 ndiff = 0, first = ~0ull, race_pages = 0, stale_pages = 0, missed_pages = 0;
            for (u64 i = 0; i < size;) {
                const VAddr a = v.base_address + i;
                const u64 page_end = std::min<u64>(size, i + (0x1000 - (a & 0xfff)));
                u64 nd = 0;
                for (u64 j = i; j < page_end; ++j) {
                    nd += ptr[j] != guest[j];
                }
                if (nd) {
                    ndiff += nd;
                    if (bc.IsRegionCpuModified(a, page_end - i)) {
                        ++race_pages;
                    } else if (bc.IsRegionGpuModified(a, page_end - i)) {
                        ++stale_pages;
                    } else {
                        ++missed_pages; // never GPU-written, not CPU-dirty, yet differs
                        if (first == ~0ull) {
                            first = i;
                        }
                    }
                }
                i = page_end;
            }
            s += fmt::format(" {}:{:x}+{:x}{}={}", static_cast<u32>(st->stage), v.base_address, size,
                             gpu ? "G" : "", ndiff);
            if (ndiff) {
                s += fmt::format("/r{}s{}m{}", race_pages, stale_pages, missed_pages);
                if (missed_pages) {
                    s += fmt::format("@{:x}", first);
                }
            }
        }
    }
    Line(s);
}
// flags/watch.txt: "start end" hex ranges. Every GPU write binding that intersects one is logged
// once per (shader, address, size) with the flip number (MADDENDRAWPROBE must be on).
static std::vector<std::pair<VAddr, VAddr>> watch;
static std::filesystem::file_time_type watch_mtime{};
void ReloadWatch() {
    std::error_code ec;
    const auto path = Core::Nba2K14Compatibility::ModPath("flags/watch.txt");
    const auto mt = std::filesystem::last_write_time(path, ec);
    if (ec || mt == watch_mtime) {
        return;
    }
    watch_mtime = mt;
    watch.clear();
    if (std::FILE* f = std::fopen(path.c_str(), "rb")) {
        unsigned long long a, b;
        while (std::fscanf(f, "%llx %llx", &a, &b) == 2) {
            watch.emplace_back(a, b);
        }
        std::fclose(f);
    }
    LOG_WARNING(Render_Vulkan, "MADDENWATCH {} ranges", watch.size());
}
void WatchWrite(const char* what, u64 hash, VAddr addr, u64 size) {
    for (const auto& [a, b] : watch) {
        if (addr < b && addr + size > a) {
            static std::set<std::tuple<u64, VAddr, u64>> seen;
            if (seen.emplace(hash, addr, size).second) {
                LOG_WARNING(Render_Vulkan, "MADDENWATCH {} sh={:08x} {:#x}+{:#x} flip={}", what,
                            hash, addr, size, VideoCore::g_flip_counter.load());
            }
            return;
        }
    }
}
// flags/READTRAP: GPU-written ranges seen since the last trap are made no-access once; the first
// CPU touch of each page is logged by the page manager (READTRAP lines).
static std::map<VAddr, std::pair<u64, u64>> gpu_written; // addr -> (size, tag)
void NoteGpuWrite(VAddr addr, u64 size, u64 tag) {
    if (!Enabled() || addr == 0 || size == 0) {
        return;
    }
    if (gpu_written.size() >= 20000) {
        gpu_written.clear(); // rolling window: keep only recent writers
    }
    auto& e = gpu_written[addr];
    if (size > e.first) {
        e = {size, tag};
    }
}
bool TrapRequested() {
    if (!Enabled() || gpu_written.empty()) {
        return false;
    }
    static u64 checked = ~0ull;
    const u64 flip = VideoCore::g_flip_counter.load();
    if (flip == checked) {
        return false;
    }
    checked = flip;
    return std::filesystem::exists(Core::Nba2K14Compatibility::ModPath("flags/READTRAP"));
}
} // namespace MaddenProbe

void Rasterizer::Draw(bool is_indexed, u32 index_offset) {
    RENDERER_TRACE;
    static const bool cmp_enabled = Core::Nba2K14Compatibility::Flag("MADDENDRAWCMP");
    g_draw_stats[0]++;

    scheduler.PopPendingOperations();
    MaddenProbe::Tick();
    if (MaddenProbe::TrapRequested()) {
        u64 pages = 0;
        for (const auto& [addr, e] : MaddenProbe::gpu_written) {
            page_manager.TrapReads(addr, e.first, e.second);
            pages += (e.first + 0xfff) >> 12;
        }
        LOG_WARNING(Render_Vulkan, "READTRAP armed on {} ranges (~{} pages)",
                    MaddenProbe::gpu_written.size(), pages);
        MaddenProbe::gpu_written.clear();
        std::error_code ec;
        std::filesystem::remove(Core::Nba2K14Compatibility::ModPath("flags/READTRAP"), ec);
    }

    if (!FilterDraw()) {
        g_draw_stats[1]++;
        return;
    }

    const auto& regs = liverpool->regs;
    const GraphicsPipeline* pipeline = pipeline_cache.GetGraphicsPipeline();
    if (!pipeline) {
        g_draw_stats[2]++;
        return;
    }
    if (MaddenProbe::Recording()) {
        MaddenProbe::DrawLine(is_indexed ? "DI" : "D", regs, pipeline, buffer_cache,
                              fmt::format("io={}{}", index_offset,
                                          MaddenProbe::Skipped(pipeline) ? " SKIP" : ""));
    }
    if (MaddenProbe::Skipped(pipeline)) {
        return;
    }

    PrepareRenderState(pipeline);
    if (!BindResources(pipeline)) {
        g_draw_stats[3]++;
        return;
    }
    if (MaddenProbe::Recording() && cmp_enabled) {
        MaddenProbe::CompareBuffers(pipeline, buffer_cache, scheduler);
    }
    g_draw_stats[4]++;
    const auto state = BeginRendering(pipeline);

    buffer_cache.BindVertexBuffers(*pipeline, buffer_barriers);
    if (is_indexed) {
        buffer_cache.BindIndexBuffer(index_offset, buffer_barriers);
    }

    pipeline->BindResources(set_writes, buffer_barriers, push_data);
    UpdateDynamicState(pipeline, is_indexed);
    scheduler.BeginRendering(state);

    const auto& vs_info = pipeline->GetStage(Shader::LogicalStage::Vertex);
    const auto& fetch_shader = pipeline->GetFetchShader();
    const auto [vertex_offset, instance_offset] = GetDrawOffsets(regs, vs_info, fetch_shader);

    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.bindPipeline(vk::PipelineBindPoint::eGraphics, pipeline->Handle());

    if (is_indexed) {
        cmdbuf.drawIndexed(regs.num_indices, regs.num_instances.NumInstances(), 0,
                           s32(vertex_offset), instance_offset);
    } else {
        cmdbuf.draw(regs.num_indices, regs.num_instances.NumInstances(), vertex_offset,
                    instance_offset);
    }

    ResetBindings();
}

void Rasterizer::DrawIndirect(bool is_indexed, VAddr arg_address, u32 offset, u32 stride,
                              u32 max_count, VAddr count_address) {
    RENDERER_TRACE;

    scheduler.PopPendingOperations();

    if (!FilterDraw()) {
        return;
    }

    const GraphicsPipeline* pipeline = pipeline_cache.GetGraphicsPipeline();
    if (!pipeline) {
        return;
    }
    if (MaddenProbe::Recording()) {
        const u32* a = reinterpret_cast<const u32*>(arg_address + offset);
        std::string args;
        for (u32 i = 0; i < std::min<u32>(stride / 4 * std::min<u32>(max_count, 4), 20); ++i) {
            args += fmt::format("{:x},", a[i]);
        }
        MaddenProbe::DrawLine(
            is_indexed ? "XI" : "X", liverpool->regs, pipeline, buffer_cache,
            fmt::format("args={:x}+{} n{} cnt={:x} {} [{}]{}", arg_address + offset, stride,
                        max_count, count_address,
                        MaddenProbe::Mod(buffer_cache, arg_address + offset, stride * max_count),
                        args, MaddenProbe::Skipped(pipeline) ? " SKIP" : ""));
    }
    if (MaddenProbe::Skipped(pipeline)) {
        return;
    }

    PrepareRenderState(pipeline);
    if (!BindResources(pipeline)) {
        return;
    }
    const auto state = BeginRendering(pipeline);

    buffer_cache.BindVertexBuffers(*pipeline, buffer_barriers);
    if (is_indexed) {
        buffer_cache.BindIndexBuffer(0, buffer_barriers);
    }

    const auto& [buffer, base] =
        buffer_cache.ObtainBuffer(arg_address + offset, stride * max_count, false);

    VideoCore::Buffer* count_buffer{};
    u32 count_base{};
    if (count_address != 0) {
        std::tie(count_buffer, count_base) = buffer_cache.ObtainBuffer(count_address, 4, false);
    }

    if (auto barrier = buffer->GetBarrier(vk::AccessFlagBits2::eIndirectCommandRead,
                                          vk::PipelineStageFlagBits2::eDrawIndirect)) {
        buffer_barriers.emplace_back(*barrier);
    }
    if (count_buffer) {
        if (auto barrier = count_buffer->GetBarrier(vk::AccessFlagBits2::eIndirectCommandRead,
                                                    vk::PipelineStageFlagBits2::eDrawIndirect)) {
            buffer_barriers.emplace_back(*barrier);
        }
    }

    pipeline->BindResources(set_writes, buffer_barriers, push_data);
    UpdateDynamicState(pipeline, is_indexed);
    scheduler.BeginRendering(state);

    // We can safely ignore both SGPR UD indices and results of fetch shader parsing, as vertex and
    // instance offsets will be automatically applied by Vulkan from indirect args buffer.

    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.bindPipeline(vk::PipelineBindPoint::eGraphics, pipeline->Handle());

    if (is_indexed) {
        ASSERT(sizeof(VkDrawIndexedIndirectCommand) == stride);

        if (count_address != 0) {
            cmdbuf.drawIndexedIndirectCount(buffer->Handle(), base, count_buffer->Handle(),
                                            count_base, max_count, stride);
        } else {
            cmdbuf.drawIndexedIndirect(buffer->Handle(), base, max_count, stride);
        }
    } else {
        ASSERT(sizeof(VkDrawIndirectCommand) == stride);

        if (count_address != 0) {
            cmdbuf.drawIndirectCount(buffer->Handle(), base, count_buffer->Handle(), count_base,
                                     max_count, stride);
        } else {
            cmdbuf.drawIndirect(buffer->Handle(), base, max_count, stride);
        }
    }

    ResetBindings();
}

void Rasterizer::DispatchDirect() {
    RENDERER_TRACE;
    g_draw_stats[5]++;

    scheduler.PopPendingOperations();

    const auto& cs_program = liverpool->GetCsRegs();
    const ComputePipeline* pipeline = pipeline_cache.GetComputePipeline();
    if (!pipeline) {
        return;
    }

    const auto& cs = pipeline->GetStage(Shader::LogicalStage::Compute);
    MaddenProbe::Tick();
    if (MaddenProbe::Recording()) {
        MaddenProbe::Line(fmt::format("C dims={}x{}x{}{}{}", cs_program.dim_x, cs_program.dim_y,
                                      cs_program.dim_z, MaddenProbe::StageDesc(cs, buffer_cache), ""));
    }
    if (ExecuteShaderHLE(cs, liverpool->regs, cs_program, *this)) {
        return;
    }

    if (!BindResources(pipeline)) {
        return;
    }
    {   // MADDENGFX probe: the dispatch that writes Madden's VideoOut buffers
        static std::set<u64> seen;
        for (const auto image_id : bound_images) {
            const auto& img = texture_cache.GetImage(image_id).info;
            if (img.guest_address >= 0x115de00000ULL && img.guest_address < 0x115f600000ULL &&
                seen.insert(cs.pgm_hash).second) {
                std::string list;
                for (const auto id2 : bound_images) {
                    const auto& i2 = texture_cache.GetImage(id2).info;
                    list += fmt::format(" [id{} {}x{} {} {:#x}]", id2.index, i2.size.width,
                                        i2.size.height, vk::to_string(i2.pixel_format),
                                        i2.guest_address);
                }
                LOG_INFO(Render_Vulkan, "MADDENGFX present-cs hash={:#x} dims={}x{}x{} images:{}",
                         cs.pgm_hash, cs_program.dim_x, cs_program.dim_y, cs_program.dim_z, list);
                u32 bi = 0;
                for (const auto& [buf_id, vsharp, bsize] : buffer_bindings) {
                    const VAddr base = vsharp.base_address;
                    std::string words;
                    if (base != 0) {
                        const u32* w = reinterpret_cast<const u32*>(base);
                        for (u32 k = 0; k < 32 && k * 4 < bsize; ++k) {
                            words += fmt::format(" {:08x}", w[k]);
                        }
                    }
                    LOG_INFO(Render_Vulkan, "MADDENGFX present-cs buf{} addr={:#x} size={:#x}:{}", bi++,
                             base, bsize, words);
                    if (bsize == 0x3f48) {
                        g_mask_addr.store(base);
                    }
                }
                break;
            }
        }
    }

    scheduler.EndRendering();

    // Madden 20 (flags/UIMASKFILL): the present pass composites UI only on 4x4 tiles set in a
    // coverage mask that cs 0xf403f253 derives from the UI target's CMASK. shadPS4 never updates
    // CMASK, so the mask is all zero and the frame is black. Mark every tile as covered: untouched
    // tiles have UI alpha 0, so compositing them is a no-op.
    // The mask size depends on the output resolution (0x3f48 at 1080p; 0xfd20 in PS4 Pro mode,
    // 3840x2160 output), so the mask is identified as the buffer cs 0xf403f253 last wrote.
    static const bool ui_mask_fill = Core::Nba2K14Compatibility::Flag("UIMASKFILL");
    static VAddr ui_mask_addr = 0;
    if (ui_mask_fill && cs.pgm_hash == 0xf403f253) {
        for (const auto& desc : cs.buffers) {
            if (desc.is_written && !desc.IsSpecial()) {
                ui_mask_addr = desc.GetSharp(cs).base_address;
            }
        }
    }
    if (ui_mask_fill && (cs.pgm_hash == 0xb5f1cbd1 || cs.pgm_hash == 0xa21a9123)) {
        for (const auto& [buf_id, vsharp, bsize] : buffer_bindings) {
            if (!buf_id || (bsize != 0x3f48 && vsharp.base_address != ui_mask_addr)) {
                continue;
            }
            auto& buffer = buffer_cache.GetBuffer(buf_id);
            if (!buffer.IsInBounds(vsharp.base_address, bsize)) {
                static int warned = 0;
                if (warned++ < 8) {
                    LOG_WARNING(Render_Vulkan, "UIMASKFILL: mask {:#x}+{:#x} outside buffer {:#x}+{:#x}; skip",
                                vsharp.base_address, bsize, buffer.CpuAddr(), buffer.SizeBytes());
                }
                continue;
            }
            const u64 off = buffer.Offset(vsharp.base_address);
            const u64 len = bsize & ~u64(3);
            const auto fill_cmdbuf = scheduler.CommandBuffer();
            const vk::BufferMemoryBarrier2 before = {
                .srcStageMask = vk::PipelineStageFlagBits2::eAllCommands,
                .srcAccessMask = vk::AccessFlagBits2::eMemoryWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .dstAccessMask = vk::AccessFlagBits2::eTransferWrite,
                .buffer = buffer.Handle(),
                .offset = off,
                .size = len,
            };
            fill_cmdbuf.pipelineBarrier2(vk::DependencyInfo{
                .bufferMemoryBarrierCount = 1, .pBufferMemoryBarriers = &before});
            fill_cmdbuf.fillBuffer(buffer.Handle(), off, len, 0xFFFFFFFFu);
            const vk::BufferMemoryBarrier2 after = {
                .srcStageMask = vk::PipelineStageFlagBits2::eTransfer,
                .srcAccessMask = vk::AccessFlagBits2::eTransferWrite,
                .dstStageMask = vk::PipelineStageFlagBits2::eComputeShader,
                .dstAccessMask = vk::AccessFlagBits2::eShaderRead,
                .buffer = buffer.Handle(),
                .offset = off,
                .size = len,
            };
            fill_cmdbuf.pipelineBarrier2(vk::DependencyInfo{
                .bufferMemoryBarrierCount = 1, .pBufferMemoryBarriers = &after});
        }
    }

    pipeline->BindResources(set_writes, buffer_barriers, push_data);

    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline->Handle());
    cmdbuf.dispatch(cs_program.dim_x, cs_program.dim_y, cs_program.dim_z);

    // Madden 20 (flags/MADDENCOPYMIRROR): cs 0x5b69b9f8 is Frostbite's GPU memcpy (CPU staging ->
    // GPU pools, e.g. 64-byte object transforms). Its output only exists in the host buffer; when the
    // CPU later writes anything else in the same 4 KiB page, the whole page is re-uploaded from guest
    // memory and the copied records are replaced with stale data -> meshes drawn with other objects'
    // transforms (cars/trees on the field). Mirror the copy into guest memory so uploads stay correct.
    static const bool copy_mirror = Core::Nba2K14Compatibility::Flag("MADDENCOPYMIRROR");
    if (copy_mirror && cs.pgm_hash == 0x5b69b9f8) {
        VAddr src = 0, dst = 0;
        u64 src_size = 0, dst_size = 0;
        for (u32 i = 0; i < cs.buffers.size() && i < buffer_bindings.size(); ++i) {
            const auto& d = cs.buffers[i];
            const auto& [buf_id, vsharp, bsize] = buffer_bindings[i];
            if (d.IsSpecial() || bsize == 0) {
                continue;
            }
            if (d.is_written) {
                dst = vsharp.base_address;
                dst_size = bsize;
            } else if (bsize > 0x10) {
                src = vsharp.base_address;
                src_size = bsize;
            }
        }
        const u64 n = std::min(src_size, dst_size);
        static u32 verified = 0;
        if (src && dst && n && !buffer_cache.IsRegionGpuModified(src, n)) {
            if (verified < 20) {
                ++verified;
                auto& dl = buffer_cache.GetUtilityBuffer(VideoCore::MemoryUsage::Download);
                const auto [ptr, off] = dl.Map(n);
                dl.Commit();
                auto& dbuf = buffer_cache.GetBuffer(buffer_cache.FindBuffer(dst, static_cast<u32>(n)));
                const vk::MemoryBarrier2 mb{
                    .srcStageMask = vk::PipelineStageFlagBits2::eComputeShader,
                    .srcAccessMask = vk::AccessFlagBits2::eShaderWrite,
                    .dstStageMask = vk::PipelineStageFlagBits2::eTransfer,
                    .dstAccessMask = vk::AccessFlagBits2::eTransferRead,
                };
                scheduler.CommandBuffer().pipelineBarrier2(
                    vk::DependencyInfo{.memoryBarrierCount = 1, .pMemoryBarriers = &mb});
                scheduler.CommandBuffer().copyBuffer(dbuf.Handle(), dl.Handle(),
                                                     vk::BufferCopy{dbuf.Offset(dst), off, n});
                scheduler.Finish();
                u64 nd = 0;
                const u8* g = reinterpret_cast<const u8*>(src);
                for (u64 k = 0; k < n; ++k) {
                    nd += ptr[k] != g[k];
                }
                const u32* c = nullptr;
                for (const auto& [bid, vs, bs] : buffer_bindings) {
                    if (bs == 0x10) {
                        c = reinterpret_cast<const u32*>(vs.base_address);
                    }
                }
                LOG_WARNING(Render_Vulkan,
                            "MADDENCOPYMIRROR verify src={:#x} dst={:#x} n={:#x} dims={} gpu_vs_src_diff={} "
                            "cb={:x},{:x},{:x},{:x}",
                            src, dst, n, cs_program.dim_x, nd, c ? c[0] : 0, c ? c[1] : 0,
                            c ? c[2] : 0, c ? c[3] : 0);
            }
            std::memcpy(reinterpret_cast<void*>(dst), reinterpret_cast<const void*>(src), n);
        }
    }

    ResetBindings();
}

void Rasterizer::DispatchIndirect(VAddr address, u32 offset, u32 size) {
    RENDERER_TRACE;

    scheduler.PopPendingOperations();

    const auto& cs_program = liverpool->GetCsRegs();
    const ComputePipeline* pipeline = pipeline_cache.GetComputePipeline();
    if (!pipeline) {
        return;
    }

    if (MaddenProbe::Recording()) {
        const u32* a = reinterpret_cast<const u32*>(address + offset);
        MaddenProbe::Line(fmt::format(
            "CX args={:x} {} [{:x},{:x},{:x}]{}", address + offset,
            MaddenProbe::Mod(buffer_cache, address + offset, size), a[0], a[1], a[2],
            MaddenProbe::StageDesc(pipeline->GetStage(Shader::LogicalStage::Compute),
                                   buffer_cache)));
    }
    if (!BindResources(pipeline)) {
        return;
    }

    const auto [buffer, base] = buffer_cache.ObtainBuffer(address + offset, size, false);

    if (auto barrier = buffer->GetBarrier(vk::AccessFlagBits2::eIndirectCommandRead,
                                          vk::PipelineStageFlagBits2::eDrawIndirect)) {
        buffer_barriers.emplace_back(*barrier);
    }

    scheduler.EndRendering();
    pipeline->BindResources(set_writes, buffer_barriers, push_data);

    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.bindPipeline(vk::PipelineBindPoint::eCompute, pipeline->Handle());
    cmdbuf.dispatchIndirect(buffer->Handle(), base);

    ResetBindings();
}

u64 Rasterizer::Flush() {
    const u64 current_tick = scheduler.CurrentTick();
    SubmitInfo info{};
    scheduler.Flush(info);
    return current_tick;
}

void Rasterizer::Finish() {
    scheduler.Finish();
}

void Rasterizer::OnSubmit() {
    if (fault_process_pending) {
        fault_process_pending = false;
        buffer_cache.ProcessFaultBuffer();
    }
    texture_cache.ProcessDownloadImages();
    texture_cache.RunGarbageCollector();
    buffer_cache.RunGarbageCollector();
}

bool Rasterizer::BindResources(const Pipeline* pipeline) {
    if (IsComputeImageCopy(pipeline) || IsComputeMetaClear(pipeline) ||
        IsComputeImageClear(pipeline)) {
        return false;
    }

    set_write_index = 0;
    set_writes.clear();
    buffer_barriers.clear();
    buffer_infos.clear();
    image_infos.clear();

    bool uses_dma = false;

    // Bind resource buffers and textures.
    Shader::Backend::Bindings binding{};
    push_data = MakeUserData(liverpool->regs);
    for (const auto* stage : pipeline->GetStages()) {
        if (!stage) {
            continue;
        }
        set_writes.resize(set_writes.size() + stage->buffers.size() + stage->images.size() +
                          stage->samplers.size());
        stage->PushUd(binding, push_data);
        BindBuffers(*stage, binding, push_data);
        BindTextures(*stage, binding);
        uses_dma |= stage->uses_dma;
    }

    if (uses_dma) {
        // We only use fault buffer for DMA right now.
        Common::RecursiveSharedLock lock{mapped_ranges_mutex};
        for (auto& range : mapped_ranges) {
            buffer_cache.SynchronizeBuffersInRange(range.lower(), range.upper() - range.lower());
        }
        fault_process_pending = true;
    }

    return true;
}

bool Rasterizer::IsComputeMetaClear(const Pipeline* pipeline) {
    if (!pipeline->IsCompute()) {
        return false;
    }

    // Most of the time when a metadata is updated with a shader it gets cleared. It means
    // we can skip the whole dispatch and update the tracked state instead. Also, it is not
    // intended to be consumed and in such rare cases (e.g. HTile introspection, CRAA) we
    // will need its full emulation anyways.
    const auto& info = pipeline->GetStage(Shader::LogicalStage::Compute);

    static const bool meta_log = Core::Nba2K14Compatibility::Flag("MADDENMETALOG");
    static std::set<std::pair<u64, VAddr>> meta_seen;

    // Assume if a shader reads metadata, it is a copy shader.
    for (const auto& desc : info.buffers) {
        const VAddr address = desc.GetSharp(info).base_address;
        if (!desc.IsSpecial() && !desc.is_written && texture_cache.IsMeta(address)) {
            if (meta_log && meta_seen.emplace(info.pgm_hash, address).second) {
                LOG_WARNING(Render_Vulkan, "MADDENMETALOG buf-read {} addr={:#x} cs={:#x} size={:#x}",
                            texture_cache.MetaTypeName(address), address, info.pgm_hash,
                            desc.GetSharp(info).GetSize());
            }
            return false;
        }
    }

    // Metadata surfaces are tiled and thus need address calculation to be written properly.
    // If a shader wants to encode HTILE, for example, from a depth image it will have to compute
    // proper tile address from dispatch invocation id. This address calculation contains an xor
    // operation so use it as a heuristic for metadata writes that are probably not clears.
    if (!info.has_bitwise_xor) {
        // Assume if a shader writes metadata without address calculation, it is a clear shader.
        for (const auto& desc : info.buffers) {
            const VAddr address = desc.GetSharp(info).base_address;
            if (!desc.IsSpecial() && desc.is_written && texture_cache.IsMeta(address)) {
                if (meta_log && meta_seen.emplace(info.pgm_hash ^ 1, address).second) {
                    LOG_WARNING(Render_Vulkan,
                                "MADDENMETALOG SKIPPED dispatch (assumed meta clear) {} addr={:#x} cs={:#x} "
                                "size={:#x} nbuf={} nimg={}",
                                texture_cache.MetaTypeName(address), address, info.pgm_hash,
                                desc.GetSharp(info).GetSize(), info.buffers.size(), info.images.size());
                }
                texture_cache.ClearMeta(address);
                // Madden 20 (flags/MADDENMETAEXEC): surface_metas is never pruned, and Madden reuses
                // memory, so this fill (cs 0x3475fc53) often targets a former HTILE/CMASK address that
                // now holds an ordinary buffer. Keep the clear-tracking above but still run the fill.
                static const bool meta_exec = Core::Nba2K14Compatibility::Flag("MADDENMETAEXEC");
                if (meta_exec) {
                    return false;
                }
                // Assume all slices were updates
                LOG_TRACE(Render_Vulkan, "Metadata update skipped");
                return true;
            }
        }
    }
    return false;
}

bool Rasterizer::IsComputeImageCopy(const Pipeline* pipeline) {
    if (!pipeline->IsCompute()) {
        return false;
    }

    // Ensure shader only has 2 bound buffers
    const auto& cs_pgm = liverpool->GetCsRegs();
    const auto& info = pipeline->GetStage(Shader::LogicalStage::Compute);
    if (cs_pgm.num_thread_x.full != 64 || info.buffers.size() != 2 || !info.images.empty()) {
        return false;
    }

    // Those 2 buffers must both be formatted. One must be source and another destination.
    const auto& desc0 = info.buffers[0];
    const auto& desc1 = info.buffers[1];
    if (!desc0.is_formatted || !desc1.is_formatted || desc0.is_written == desc1.is_written) {
        return false;
    }

    // Buffers must have the same size and each thread of the dispatch must copy 1 dword of data
    const AmdGpu::Buffer buf0 = desc0.GetSharp(info);
    const AmdGpu::Buffer buf1 = desc1.GetSharp(info);
    if (buf0.GetSize() != buf1.GetSize() || cs_pgm.dim_x != (buf0.GetSize() / 256)) {
        return false;
    }

    // Find images the buffer alias
    const auto image0_id = texture_cache.FindImageFromRange(buf0.base_address, buf0.GetSize());
    if (!image0_id) {
        return false;
    }
    const auto image1_id =
        texture_cache.FindImageFromRange(buf1.base_address, buf1.GetSize(), false);
    if (!image1_id) {
        return false;
    }

    // Image copy must be valid
    VideoCore::Image& image0 = texture_cache.GetImage(image0_id);
    VideoCore::Image& image1 = texture_cache.GetImage(image1_id);
    if (image0.info.guest_size != image1.info.guest_size ||
        image0.info.pitch != image1.info.pitch || image0.info.guest_size != buf0.GetSize() ||
        image0.info.num_bits != image1.info.num_bits) {
        return false;
    }

    // Perform image copy
    VideoCore::Image& src_image = desc0.is_written ? image1 : image0;
    VideoCore::Image& dst_image = desc0.is_written ? image0 : image1;
    if (instance.IsMaintenance8Supported() ||
        src_image.info.props.is_depth == dst_image.info.props.is_depth) {
        dst_image.CopyImage(src_image);
    } else {
        const auto& copy_buffer =
            buffer_cache.GetUtilityBuffer(VideoCore::MemoryUsage::DeviceLocal);
        dst_image.CopyImageWithBuffer(src_image, copy_buffer.Handle(), 0);
    }
    dst_image.flags |= VideoCore::ImageFlagBits::GpuModified;
    dst_image.flags &= ~VideoCore::ImageFlagBits::Dirty;
    return true;
}

bool Rasterizer::IsComputeImageClear(const Pipeline* pipeline) {
    if (!pipeline->IsCompute()) {
        return false;
    }

    // Ensure shader only has 2 bound buffers
    const auto& cs_pgm = liverpool->GetCsRegs();
    const auto& info = pipeline->GetStage(Shader::LogicalStage::Compute);
    if (cs_pgm.num_thread_x.full != 64 || info.buffers.size() != 2 || !info.images.empty()) {
        return false;
    }

    // From those 2 buffers, first must hold the clear vector and second the image being cleared
    const auto& desc0 = info.buffers[0];
    const auto& desc1 = info.buffers[1];
    if (desc0.is_formatted || !desc1.is_formatted || desc0.is_written || !desc1.is_written) {
        return false;
    }

    // First buffer must have size of vec4 and second the size of a single layer
    const AmdGpu::Buffer buf0 = desc0.GetSharp(info);
    const AmdGpu::Buffer buf1 = desc1.GetSharp(info);
    const u32 buf1_bpp = AmdGpu::NumBitsPerBlock(buf1.GetDataFmt());
    if (buf0.GetSize() != 16 || (cs_pgm.dim_x * 128ULL * (buf1_bpp / 8)) != buf1.GetSize()) {
        return false;
    }

    // Find image the buffer alias
    const auto image1_id =
        texture_cache.FindImageFromRange(buf1.base_address, buf1.GetSize(), false);
    if (!image1_id) {
        return false;
    }

    // Image clear must be valid
    VideoCore::Image& image1 = texture_cache.GetImage(image1_id);
    if (image1.info.guest_size != buf1.GetSize() || image1.info.num_bits != buf1_bpp ||
        image1.info.props.is_depth) {
        return false;
    }

    // Perform image clear
    const float* values = reinterpret_cast<float*>(buf0.base_address);
    const vk::ClearValue clear = {
        .color = {.float32 = std::array<float, 4>{values[0], values[1], values[2], values[3]}},
    };
    const VideoCore::SubresourceRange range = {
        .base =
            {
                .level = 0,
                .layer = 0,
            },
        .extent = image1.info.resources,
    };
    image1.Clear(clear, range);
    image1.flags |= VideoCore::ImageFlagBits::GpuModified;
    image1.flags &= ~VideoCore::ImageFlagBits::Dirty;
    return true;
}

void Rasterizer::BindBuffers(const Shader::Info& stage, Shader::Backend::Bindings& binding,
                             Shader::PushData& push_data) {
    buffer_bindings.clear();

    for (const auto& desc : stage.buffers) {
        const auto vsharp = desc.GetSharp(stage);
        if (!desc.IsSpecial() && vsharp.base_address != 0 && vsharp.GetSize() > 0) {
            const u64 size = memory->ClampRangeSize(vsharp.base_address, vsharp.GetSize());
            const auto buffer_id = buffer_cache.FindBuffer(vsharp.base_address, size);
            buffer_bindings.emplace_back(buffer_id, vsharp, size);
        } else {
            buffer_bindings.emplace_back(VideoCore::BufferId{}, vsharp, 0);
        }
    }

    // Second pass to re-bind buffers that were updated after binding
    for (u32 i = 0; i < buffer_bindings.size(); i++) {
        const auto& [buffer_id, vsharp, size] = buffer_bindings[i];
        const auto& desc = stage.buffers[i];
        const bool is_storage = desc.IsStorage(vsharp);
        const u32 alignment =
            is_storage ? instance.StorageMinAlignment() : instance.UniformMinAlignment();
        // Buffer is not from the cache, either a special buffer or unbound.
        if (!buffer_id) {
            if (desc.buffer_type == Shader::BufferType::GdsBuffer) {
                const auto* gds_buf = buffer_cache.GetGdsBuffer();
                buffer_infos.emplace_back(gds_buf->Handle(), 0, gds_buf->SizeBytes());
            } else if (desc.buffer_type == Shader::BufferType::Flatbuf) {
                auto& vk_buffer = buffer_cache.GetUtilityBuffer(VideoCore::MemoryUsage::Stream);
                const u32 ubo_size = stage.flattened_ud_buf.size() * sizeof(u32);
                const u64 offset =
                    vk_buffer.Copy(stage.flattened_ud_buf.data(), ubo_size, alignment);
                buffer_infos.emplace_back(vk_buffer.Handle(), offset, ubo_size);
            } else if (desc.buffer_type == Shader::BufferType::BdaPagetable) {
                const auto* bda_buffer = buffer_cache.GetBdaPageTableBuffer();
                buffer_infos.emplace_back(bda_buffer->Handle(), 0, bda_buffer->SizeBytes());
            } else if (desc.buffer_type == Shader::BufferType::FaultBuffer) {
                const auto* fault_buffer = buffer_cache.GetFaultBuffer();
                buffer_infos.emplace_back(fault_buffer->Handle(), 0, fault_buffer->SizeBytes());
            } else if (desc.buffer_type == Shader::BufferType::SharedMemory) {
                auto& lds_buffer = buffer_cache.GetUtilityBuffer(VideoCore::MemoryUsage::Stream);
                const auto& cs_program = liverpool->GetCsRegs();
                const auto lds_size = cs_program.SharedMemSize() * cs_program.NumWorkgroups();
                const auto [data, offset] = lds_buffer.Map(lds_size, alignment);
                std::memset(data, 0, lds_size);
                buffer_infos.emplace_back(lds_buffer.Handle(), offset, lds_size);
            } else {
                buffer_infos.emplace_back(VK_NULL_HANDLE, 0, VK_WHOLE_SIZE);
            }
        } else {
            if (desc.is_written) {
                MaddenProbe::NoteGpuWrite(vsharp.base_address, size, stage.pgm_hash);
                buffer_cache.NoteWriteback(vsharp.base_address, size, stage.pgm_hash);
            }
            if (desc.is_written && !MaddenProbe::watch.empty()) {
                MaddenProbe::WatchWrite("bufw", stage.pgm_hash, vsharp.base_address, size);
            }
            const auto [vk_buffer, offset] = buffer_cache.ObtainBuffer(
                vsharp.base_address, size, desc.is_written, desc.is_formatted, buffer_id);
            const u32 offset_aligned = Common::AlignDown(offset, alignment);
            const u32 adjust = offset - offset_aligned;
            ASSERT(adjust % 4 == 0);
            push_data.AddOffset(binding.buffer, adjust);
            buffer_infos.emplace_back(vk_buffer->Handle(), offset_aligned, size + adjust);
            if (auto barrier =
                    vk_buffer->GetBarrier(desc.is_written ? vk::AccessFlagBits2::eShaderWrite
                                                          : vk::AccessFlagBits2::eShaderRead,
                                          vk::PipelineStageFlagBits2::eAllCommands)) {
                buffer_barriers.emplace_back(*barrier);
            }
            if (desc.is_written && desc.is_formatted) {
                texture_cache.InvalidateMemoryFromGPU(vsharp.base_address, size);
            }
        }

        auto& set_write = set_writes[set_write_index++];
        set_write.dstSet = VK_NULL_HANDLE;
        set_write.dstBinding = binding.unified++;
        set_write.dstArrayElement = 0;
        set_write.descriptorCount = 1;
        set_write.descriptorType =
            is_storage ? vk::DescriptorType::eStorageBuffer : vk::DescriptorType::eUniformBuffer;
        set_write.pBufferInfo = &buffer_infos.back();
        ++binding.buffer;
    }
}

void Rasterizer::BindTextures(const Shader::Info& stage, Shader::Backend::Bindings& binding) {
    image_bindings.clear();
    const u32 first_image_idx = image_infos.size();
    // For loading/storing to explicit mip levels, when no native instruction support, bind an array
    // of descriptors consecutively, 1 for each mip level. The shader can index this with LOD
    // operand.
    // This array holds the size of each consecutive array with the number of bindings consumed.
    // This is currently always 1 for anything other than mip fallback arrays.
    boost::container::small_vector<u32, 8> image_descriptor_array_sizes;

    for (const auto& image_desc : stage.images) {
        const auto tsharp = image_desc.GetSharp(stage);
        if (texture_cache.IsMeta(tsharp.Address())) {
            LOG_WARNING(Render_Vulkan, "Unexpected metadata read by a shader (texture)");
            // Madden 20 (flags/MADDENMETALOG): once per (shader, surface), say what is being read.
            static const bool meta_log = Core::Nba2K14Compatibility::Flag("MADDENMETALOG");
            static std::set<std::pair<u64, VAddr>> meta_seen;
            if (meta_log && meta_seen.emplace(stage.pgm_hash, tsharp.Address()).second) {
                LOG_WARNING(Render_Vulkan,
                            "MADDENMETALOG tex-read {} addr={:#x} shader={:#x} stage={} fmt={} nfmt={} "
                            "{}x{} pitch={} tile={}",
                            texture_cache.MetaTypeName(tsharp.Address()), tsharp.Address(),
                            stage.pgm_hash, u32(stage.stage), u32(tsharp.GetDataFmt()),
                            u32(tsharp.GetNumberFmt()), tsharp.width + 1, tsharp.height + 1,
                            tsharp.Pitch(), u32(tsharp.GetTileMode()));
            }
        }

        if (tsharp.Address() == 0 || tsharp.GetDataFmt() == AmdGpu::DataFormat::FormatInvalid) {
            image_bindings.emplace_back(std::piecewise_construct, std::tuple{}, std::tuple{});
            image_descriptor_array_sizes.push_back(1);
            continue;
        }

        const Shader::MipStorageFallbackMode mip_fallback_mode = image_desc.mip_fallback_mode;
        const u32 num_bindings = image_desc.NumBindings(stage);

        for (auto i = 0; i < num_bindings; i++) {
            auto& [image_id, desc] = image_bindings.emplace_back(
                std::piecewise_construct, std::tuple{}, std::tuple{tsharp, image_desc});

            if (mip_fallback_mode == Shader::MipStorageFallbackMode::ConstantIndex) {
                ASSERT(num_bindings == 1);
                desc.view_info.range.base.level += image_desc.constant_mip_index;
                desc.view_info.range.extent.levels = 1;
            } else if (mip_fallback_mode == Shader::MipStorageFallbackMode::DynamicIndex) {
                desc.view_info.range.base.level += i;
                desc.view_info.range.extent.levels = 1;
            }

            image_id = texture_cache.FindImage(desc);
            auto* image = &texture_cache.GetImage(image_id);
            if (auto depth_image_id = texture_cache.GetAssociatedDepth(*image)) {
                // If this image has an associated depth image, it's a stencil attachment.
                // Redirect the access to the actual depth-stencil buffer.
                image_id = depth_image_id;
                image = &texture_cache.GetImage(image_id);
            }
            if (image->binding.is_bound) {
                // The image is already bound. In case if it is about to be used as storage we
                // need to force general layout on it.
                image->binding.force_general |= image_desc.is_written;
            }
            image->binding.is_bound = 1u;
        }

        image_descriptor_array_sizes.push_back(num_bindings);
    }

    // Second pass to re-bind images that were updated after binding
    for (auto& [image_id, desc] : image_bindings) {
        bool is_storage = desc.type == VideoCore::TextureCache::BindingType::Storage;
        if (!image_id) {
            image_infos.emplace_back(VK_NULL_HANDLE, VK_NULL_HANDLE, vk::ImageLayout::eGeneral);
        } else {
            if (auto& old_image = texture_cache.GetImage(image_id);
                old_image.binding.needs_rebind) {
                old_image.binding = {};
                image_id = texture_cache.FindImage(desc);
            }

            bound_images.emplace_back(image_id);

            auto& image = texture_cache.GetImage(image_id);
            auto& image_view = texture_cache.FindTexture(image_id, desc);

            // The image is either bound as storage in a separate descriptor or bound as render
            // target in feedback loop. Depth images are excluded because they can't be bound as
            // storage and feedback loop doesn't make sense for them
            if ((image.binding.force_general || image.binding.is_target) &&
                !image.info.props.is_depth) {
                image.Transit(instance.IsAttachmentFeedbackLoopLayoutSupported() &&
                                      image.binding.is_target
                                  ? vk::ImageLayout::eAttachmentFeedbackLoopOptimalEXT
                                  : vk::ImageLayout::eGeneral,
                              vk::AccessFlagBits2::eShaderRead |
                                  (image.info.props.is_depth
                                       ? vk::AccessFlagBits2::eDepthStencilAttachmentWrite
                                       : vk::AccessFlagBits2::eColorAttachmentWrite |
                                             vk::AccessFlagBits2::eColorAttachmentRead),
                              {});
            } else {
                if (is_storage) {
                    image.Transit(vk::ImageLayout::eGeneral,
                                  vk::AccessFlagBits2::eShaderRead |
                                      vk::AccessFlagBits2::eShaderWrite,
                                  desc.view_info.range);
                } else {
                    const auto new_layout = image.info.props.is_depth
                                                ? vk::ImageLayout::eDepthStencilReadOnlyOptimal
                                                : vk::ImageLayout::eShaderReadOnlyOptimal;
                    image.Transit(new_layout, vk::AccessFlagBits2::eShaderRead,
                                  desc.view_info.range);
                }
            }
            if (is_storage) {
                MaddenProbe::NoteGpuWrite(image.info.guest_address, image.info.guest_size,
                                          stage.pgm_hash | (1ull << 40));
            }
            if (is_storage && !MaddenProbe::watch.empty()) {
                MaddenProbe::WatchWrite("imgw", stage.pgm_hash, image.info.guest_address,
                                        image.info.guest_size);
            }
            image.usage.storage |= is_storage;
            image.usage.texture |= !is_storage;

            image_infos.emplace_back(VK_NULL_HANDLE, *image_view.image_view,
                                     image.backing->state.layout);
        }
    }

    u32 image_info_idx = first_image_idx;
    u32 image_binding_idx = 0;
    for (u32 array_size : image_descriptor_array_sizes) {
        const auto& [_, desc] = image_bindings[image_binding_idx];
        const bool is_storage = desc.type == VideoCore::TextureCache::BindingType::Storage;
        auto& set_write = set_writes[set_write_index++];
        set_write.dstSet = VK_NULL_HANDLE;
        set_write.dstBinding = binding.unified;
        set_write.dstArrayElement = 0;
        set_write.descriptorCount = array_size;
        set_write.descriptorType =
            is_storage ? vk::DescriptorType::eStorageImage : vk::DescriptorType::eSampledImage;
        set_write.pImageInfo = &image_infos[image_info_idx];

        image_info_idx += array_size;
        image_binding_idx += array_size;
        binding.unified += array_size;
    }

    for (const auto& sampler : stage.samplers) {
        auto ssharp = sampler.GetSharp(stage);
        if (sampler.disable_aniso) {
            const auto& tsharp = stage.images[sampler.associated_image].GetSharp(stage);
            if (tsharp.base_level == 0 && tsharp.last_level == 0) {
                ssharp.max_aniso.Assign(AmdGpu::AnisoRatio::One);
            }
        }
        // Madden 20 pixelated grass hunt: flags/MADDENSAMPLOG logs each point-filtered (shader,
        // sampler, texture) once; flags/MADDENLINEARMIP turns point mag/min filtering into linear
        // for samplers whose texture has a mip chain (material textures, not RT/post buffers).
        {
            static const bool samp_log = Core::Nba2K14Compatibility::Flag("MADDENSAMPLOG");
            static const bool lin_mip = Core::Nba2K14Compatibility::Flag("MADDENLINEARMIP");
            const bool mag_pt = !(static_cast<u32>(ssharp.xy_mag_filter.Value()) & 1);
            const bool min_pt = !(static_cast<u32>(ssharp.xy_min_filter.Value()) & 1);
            if ((samp_log || lin_mip) && (mag_pt || min_pt) &&
                sampler.associated_image < stage.images.size()) {
                const auto& tsharp = stage.images[sampler.associated_image].GetSharp(stage);
                const bool has_mips = tsharp.last_level > tsharp.base_level;
                if (samp_log) {
                    static std::set<std::tuple<u64, u64, u64, VAddr>> seen;
                    static std::mutex seen_mutex;
                    u64 sraw[2]{};
                    std::memcpy(sraw, &ssharp, std::min(sizeof(sraw), sizeof(ssharp)));
                    std::scoped_lock lk{seen_mutex};
                    if (seen.size() < 4000 &&
                        seen.emplace(stage.pgm_hash, sraw[0], sraw[1], tsharp.Address()).second) {
                        LOG_WARNING(Render_Vulkan,
                                    "MADDENSAMPLOG st{} {:08x} samp mag{} min{} mip{} aniso{} "
                                    "bias{:.2f} lod[{:.2f},{:.2f}] tex {:x} {}x{} f{} nf{} "
                                    "lv{}-{} {}",
                                    static_cast<u32>(stage.stage), stage.pgm_hash,
                                    static_cast<u32>(ssharp.xy_mag_filter.Value()),
                                    static_cast<u32>(ssharp.xy_min_filter.Value()),
                                    static_cast<u32>(ssharp.mip_filter.Value()),
                                    static_cast<u32>(ssharp.max_aniso.Value()), ssharp.LodBias(),
                                    ssharp.MinLod(), ssharp.MaxLod(), tsharp.Address(),
                                    tsharp.width + 1, tsharp.height + 1,
                                    static_cast<u32>(tsharp.GetDataFmt()),
                                    static_cast<u32>(tsharp.GetNumberFmt()),
                                    static_cast<u32>(tsharp.base_level),
                                    static_cast<u32>(tsharp.last_level),
                                    lin_mip && has_mips ? "->LINEAR" : "");
                    }
                }
                if (lin_mip && has_mips) {
                    if (mag_pt) {
                        ssharp.xy_mag_filter.Assign(static_cast<AmdGpu::Filter>(
                            static_cast<u32>(ssharp.xy_mag_filter.Value()) | 1));
                    }
                    if (min_pt) {
                        ssharp.xy_min_filter.Assign(static_cast<AmdGpu::Filter>(
                            static_cast<u32>(ssharp.xy_min_filter.Value()) | 1));
                    }
                }
            }
        }
        const auto vk_sampler = texture_cache.GetSampler(ssharp, liverpool->regs.ta_bc_base);
        image_infos.emplace_back(vk_sampler, VK_NULL_HANDLE, vk::ImageLayout::eGeneral);
        auto& set_write = set_writes[set_write_index++];
        set_write.dstSet = VK_NULL_HANDLE;
        set_write.dstBinding = binding.unified++;
        set_write.dstArrayElement = 0;
        set_write.descriptorCount = 1;
        set_write.descriptorType = vk::DescriptorType::eSampler;
        set_write.pImageInfo = &image_infos.back();
    }
}

RenderState Rasterizer::BeginRendering(const GraphicsPipeline* pipeline) {
    attachment_feedback_loop = false;
    const auto& regs = liverpool->regs;
    const auto& key = pipeline->GetGraphicsKey();
    RenderState state;
    state.width = instance.GetMaxFramebufferWidth();
    state.height = instance.GetMaxFramebufferHeight();
    state.num_layers = std::numeric_limits<u16>::max();
    state.num_color_attachments = std::bit_width(key.mrt_mask);
    for (auto cb = 0u; cb < state.num_color_attachments; ++cb) {
        auto& [image_id, desc] = cb_descs[cb];
        if (!image_id) {
            state.color_attachments[cb] = {};
            continue;
        }
        auto* image = &texture_cache.GetImage(image_id);
        if (image->binding.needs_rebind) {
            image_id = bound_images.emplace_back(texture_cache.FindImage(desc));
            image = &texture_cache.GetImage(image_id);
        }
        texture_cache.UpdateImage(image_id);
        image->SetBackingSamples(key.color_samples[cb]);
        const auto& image_view = texture_cache.FindRenderTarget(image_id, desc);
        const auto slice = image_view.info.range.base.layer;
        const auto mip = image_view.info.range.base.level;
        if (!MaddenProbe::watch.empty()) {
            MaddenProbe::WatchWrite("rt", (u64(mip) << 32) | u32(image->info.num_bits),
                                    image->info.guest_address, image->info.guest_size);
        }

        const auto& col_buf = regs.color_buffers[cb];
        const bool is_clear = texture_cache.IsMetaCleared(col_buf.CmaskAddress(), slice);
        texture_cache.TouchMeta(col_buf.CmaskAddress(), slice, false);

        if (image->binding.is_bound) {
            ASSERT_MSG(!image->binding.force_general,
                       "Having image both as storage and render target is unsupported");
            image->Transit(instance.IsAttachmentFeedbackLoopLayoutSupported()
                               ? vk::ImageLayout::eAttachmentFeedbackLoopOptimalEXT
                               : vk::ImageLayout::eGeneral,
                           vk::AccessFlagBits2::eColorAttachmentWrite, {});
            attachment_feedback_loop = true;
        } else {
            image->Transit(vk::ImageLayout::eColorAttachmentOptimal,
                           vk::AccessFlagBits2::eColorAttachmentWrite |
                               vk::AccessFlagBits2::eColorAttachmentRead,
                           desc.view_info.range);
        }

        state.width = std::min<u32>(state.width, std::max(image->info.size.width >> mip, 1u));
        state.height = std::min<u32>(state.height, std::max(image->info.size.height >> mip, 1u));
        state.num_layers = std::min<u32>(state.num_layers, image_view.info.range.extent.layers);

        const auto clear_value =
            is_clear ? LiverpoolToVK::ColorBufferClearValue(col_buf) : vk::ClearValue{};
        auto& attachment = state.color_attachments[cb];
        attachment.image_view = *image_view.image_view;
        attachment.image_layout = image->backing->state.layout;
        attachment.clear_value = clear_value.color.uint32;
        attachment.is_clear = is_clear;

        image->usage.render_target = 1u;
        MaddenProbe::NoteGpuWrite(image->info.guest_address, image->info.guest_size,
                                  (2ull << 40) | image->info.size.width << 16 | image->info.size.height);
    }
    for (u32 cb = state.num_color_attachments; cb < state.color_attachments.size(); ++cb) {
        state.color_attachments[cb] = {};
    }

    if (auto image_id = db_desc.first; image_id) {
        auto& desc = db_desc.second;
        const auto htile_address = regs.depth_htile_data_base.GetAddress();
        const auto& image_view = texture_cache.FindDepthTarget(image_id, desc);
        auto& image = texture_cache.GetImage(image_id);
        MaddenProbe::NoteGpuWrite(image.info.guest_address, image.info.guest_size,
                                  (3ull << 40) | image.info.size.width << 16 | image.info.size.height);

        const auto slice = image_view.info.range.base.layer;
        const bool is_depth_clear =
            (regs.depth_render_control.depth_clear_enable && regs.depth_control.depth_enable &&
             regs.depth_control.depth_write_enable) ||
            texture_cache.IsMetaCleared(htile_address, slice);
        const bool is_stencil_clear = regs.depth_render_control.stencil_clear_enable;
        texture_cache.TouchMeta(htile_address, slice, false);
        ASSERT(desc.view_info.range.extent.levels == 1 && !image.binding.needs_rebind);

        const bool has_stencil = image.info.props.has_stencil;
        // Stencil writes can be enabled while depth writes are off.
        const bool stencil_write =
            has_stencil && regs.depth_control.stencil_enable && !desc.view_info.is_storage;
        const auto new_layout = desc.view_info.is_storage
                                    ? has_stencil ? vk::ImageLayout::eDepthStencilAttachmentOptimal
                                                  : vk::ImageLayout::eDepthAttachmentOptimal
                                : stencil_write
                                    ? vk::ImageLayout::eDepthReadOnlyStencilAttachmentOptimal
                                : has_stencil ? vk::ImageLayout::eDepthStencilReadOnlyOptimal
                                              : vk::ImageLayout::eDepthReadOnlyOptimal;
        image.Transit(new_layout,
                      vk::AccessFlagBits2::eDepthStencilAttachmentWrite |
                          vk::AccessFlagBits2::eDepthStencilAttachmentRead,
                      desc.view_info.range);

        state.width = std::min<u32>(state.width, image.info.size.width);
        state.height = std::min<u32>(state.height, image.info.size.height);
        state.num_layers = std::min<u32>(state.num_layers, image_view.info.range.extent.layers);

        auto& attachment = state.depth_stencil_attachment;
        attachment.image_view = *image_view.image_view;
        attachment.image_layout = image.backing->state.layout;
        attachment.clear_value = {};

        if (regs.depth_buffer.DepthValid()) {
            attachment.clear_value[0] = is_depth_clear ? std::bit_cast<u32>(regs.depth_clear) : 0u;
            attachment.has_depth = true;
            attachment.depth_clear = is_depth_clear;
        }
        if (regs.depth_buffer.StencilValid()) {
            attachment.clear_value[1] = is_stencil_clear ? regs.stencil_clear : 0u;
            attachment.has_stencil = true;
            attachment.stencil_clear = is_stencil_clear;
        }

        image.usage.depth_target = true;
    } else {
        state.depth_stencil_attachment = {};
    }

    if (state.num_layers == std::numeric_limits<u16>::max()) {
        state.num_layers = 1;
    }

    return state;
}

void Rasterizer::Resolve() {
    const auto& mrt0_hint = liverpool->last_cb_extent[0];
    const auto& mrt1_hint = liverpool->last_cb_extent[1];
    VideoCore::TextureCache::ImageDesc mrt0_desc{liverpool->regs.color_buffers[0], mrt0_hint};
    VideoCore::TextureCache::ImageDesc mrt1_desc{liverpool->regs.color_buffers[1], mrt1_hint};
    auto& mrt0_image = texture_cache.GetImage(texture_cache.FindImage(mrt0_desc, true));
    auto& mrt1_image = texture_cache.GetImage(texture_cache.FindImage(mrt1_desc, true));

    ScopeMarkerBegin(fmt::format("Resolve:MRT0={:#x}:MRT1={:#x}",
                                 liverpool->regs.color_buffers[0].Address(),
                                 liverpool->regs.color_buffers[1].Address()));
    mrt1_image.Resolve(mrt0_image, mrt0_desc.view_info.range, mrt1_desc.view_info.range);
    ScopeMarkerEnd();
}

void Rasterizer::DepthStencilCopy(bool is_depth, bool is_stencil) {
    auto& regs = liverpool->regs;

    auto read_desc = VideoCore::TextureCache::ImageDesc(
        regs.depth_buffer, regs.depth_view, regs.depth_control,
        regs.depth_htile_data_base.GetAddress(), liverpool->last_db_extent, false);
    auto write_desc = VideoCore::TextureCache::ImageDesc(
        regs.depth_buffer, regs.depth_view, regs.depth_control,
        regs.depth_htile_data_base.GetAddress(), liverpool->last_db_extent, true);

    auto& read_image = texture_cache.GetImage(texture_cache.FindImage(read_desc));
    auto& write_image = texture_cache.GetImage(texture_cache.FindImage(write_desc));

    VideoCore::SubresourceRange sub_range;
    sub_range.base.layer = liverpool->regs.depth_view.slice_start;
    sub_range.extent.layers = liverpool->regs.depth_view.NumSlices() - sub_range.base.layer;

    ScopeMarkerBegin(fmt::format(
        "DepthStencilCopy:DR={:#x}:SR={:#x}:DW={:#x}:SW={:#x}", regs.depth_buffer.DepthAddress(),
        regs.depth_buffer.StencilAddress(), regs.depth_buffer.DepthWriteAddress(),
        regs.depth_buffer.StencilWriteAddress()));

    read_image.Transit(vk::ImageLayout::eTransferSrcOptimal, vk::AccessFlagBits2::eTransferRead,
                       sub_range);
    write_image.Transit(vk::ImageLayout::eTransferDstOptimal, vk::AccessFlagBits2::eTransferWrite,
                        sub_range);

    auto aspect_mask = vk::ImageAspectFlags(0);
    if (is_depth) {
        aspect_mask |= vk::ImageAspectFlagBits::eDepth;
    }
    if (is_stencil) {
        aspect_mask |= vk::ImageAspectFlagBits::eStencil;
    }

    vk::ImageCopy region = {
        .srcSubresource =
            {
                .aspectMask = aspect_mask,
                .mipLevel = 0,
                .baseArrayLayer = sub_range.base.layer,
                .layerCount = sub_range.extent.layers,
            },
        .srcOffset = {0, 0, 0},
        .dstSubresource =
            {
                .aspectMask = aspect_mask,
                .mipLevel = 0,
                .baseArrayLayer = sub_range.base.layer,
                .layerCount = sub_range.extent.layers,
            },
        .dstOffset = {0, 0, 0},
        .extent = {write_image.info.size.width, write_image.info.size.height, 1},
    };
    scheduler.CommandBuffer().copyImage(read_image.GetImage(), vk::ImageLayout::eTransferSrcOptimal,
                                        write_image.GetImage(),
                                        vk::ImageLayout::eTransferDstOptimal, region);

    ScopeMarkerEnd();
}

void Rasterizer::FillBuffer(VAddr address, u32 num_bytes, u32 value, bool is_gds) {
    if (!is_gds && !MaddenProbe::watch.empty()) {
        MaddenProbe::WatchWrite(buffer_cache.IsRegionGpuModified(address, num_bytes) ? "fillG" : "fill",
                                value, address, num_bytes);
    }
    buffer_cache.FillBuffer(address, num_bytes, value, is_gds);
}

void Rasterizer::CopyBuffer(VAddr dst, VAddr src, u32 num_bytes, bool dst_gds, bool src_gds) {
    if (!dst_gds && !MaddenProbe::watch.empty()) {
        MaddenProbe::WatchWrite("copy", src, dst, num_bytes);
    }
    buffer_cache.CopyBuffer(dst, src, num_bytes, dst_gds, src_gds);
}

u32 Rasterizer::ReadDataFromGds(u32 gds_offset) {
    auto* gds_buf = buffer_cache.GetGdsBuffer();
    u32 value;
    std::memcpy(&value, gds_buf->mapped_data.data() + gds_offset, sizeof(u32));
    return value;
}

bool Rasterizer::InvalidateMemory(VAddr addr, u64 size) {
    if (!IsMapped(addr, size)) {
        // Not GPU mapped memory, can skip invalidation logic entirely.
        return false;
    }
    buffer_cache.InvalidateMemory(addr, size);
    texture_cache.InvalidateMemory(addr, size);
    return true;
}

bool Rasterizer::ReadMemory(VAddr addr, u64 size) {
    if (!IsMapped(addr, size)) {
        // Not GPU mapped memory, can skip invalidation logic entirely.
        return false;
    }
    buffer_cache.ReadMemory(addr, size);
    return true;
}

void Rasterizer::ProcessDownloadImages() {
    texture_cache.ProcessDownloadImages();
    buffer_cache.FlushWritebacks();
}

bool Rasterizer::IsMapped(VAddr addr, u64 size) {
    if (size == 0) {
        // There is no memory, so not mapped.
        return false;
    }
    if (static_cast<u64>(addr) > std::numeric_limits<u64>::max() - size) {
        // Memory range wrapped the address space, cannot be mapped.
        return false;
    }
    const auto range = decltype(mapped_ranges)::interval_type::right_open(addr, addr + size);

    Common::RecursiveSharedLock lock{mapped_ranges_mutex};
    return boost::icl::contains(mapped_ranges, range);
}

void Rasterizer::MapMemory(VAddr addr, u64 size) {
    {
        std::scoped_lock lock{mapped_ranges_mutex};
        mapped_ranges += decltype(mapped_ranges)::interval_type::right_open(addr, addr + size);
    }
    page_manager.OnGpuMap(addr, size);
}

void Rasterizer::UnmapMemory(VAddr addr, u64 size) {
    buffer_cache.InvalidateMemory(addr, size);
    texture_cache.UnmapMemory(addr, size);
    page_manager.OnGpuUnmap(addr, size);
    {
        std::scoped_lock lock{mapped_ranges_mutex};
        mapped_ranges -= decltype(mapped_ranges)::interval_type::right_open(addr, addr + size);
    }
}

void Rasterizer::UpdateDynamicState(const GraphicsPipeline* pipeline, const bool is_indexed) const {
    UpdateViewportScissorState();
    UpdateDepthStencilState();
    UpdatePrimitiveState(is_indexed);
    UpdateRasterizationState();
    UpdateColorBlendingState(pipeline);

    auto& dynamic_state = scheduler.GetDynamicState();
    dynamic_state.Commit(instance, scheduler.CommandBuffer());
}

void Rasterizer::UpdateViewportScissorState() const {
    const auto& regs = liverpool->regs;

    const auto combined_scissor_value_tl = [](s16 scr, s16 win, s16 gen, s16 win_offset) {
        return std::max({scr, s16(win + win_offset), s16(gen + win_offset)});
    };
    const auto combined_scissor_value_br = [](s16 scr, s16 win, s16 gen, s16 win_offset) {
        return std::min({scr, s16(win + win_offset), s16(gen + win_offset)});
    };
    const bool enable_offset = !regs.window_scissor.window_offset_disable;

    AmdGpu::Scissor scsr{};
    scsr.top_left_x = combined_scissor_value_tl(
        regs.screen_scissor.top_left_x, s16(regs.window_scissor.top_left_x),
        s16(regs.generic_scissor.top_left_x),
        enable_offset ? regs.window_offset.window_x_offset : 0);
    scsr.top_left_y = combined_scissor_value_tl(
        regs.screen_scissor.top_left_y, s16(regs.window_scissor.top_left_y),
        s16(regs.generic_scissor.top_left_y),
        enable_offset ? regs.window_offset.window_y_offset : 0);
    scsr.bottom_right_x = combined_scissor_value_br(
        regs.screen_scissor.bottom_right_x, regs.window_scissor.bottom_right_x,
        regs.generic_scissor.bottom_right_x,
        enable_offset ? regs.window_offset.window_x_offset : 0);
    scsr.bottom_right_y = combined_scissor_value_br(
        regs.screen_scissor.bottom_right_y, regs.window_scissor.bottom_right_y,
        regs.generic_scissor.bottom_right_y,
        enable_offset ? regs.window_offset.window_y_offset : 0);

    boost::container::static_vector<vk::Viewport, AmdGpu::NUM_VIEWPORTS> viewports;
    boost::container::static_vector<vk::Rect2D, AmdGpu::NUM_VIEWPORTS> scissors;

    if (regs.polygon_control.enable_window_offset &&
        (regs.window_offset.window_x_offset != 0 || regs.window_offset.window_y_offset != 0)) {
        LOG_ERROR(Render_Vulkan,
                  "PA_SU_SC_MODE_CNTL.VTX_WINDOW_OFFSET_ENABLE support is not yet implemented.");
    }

    const auto& vp_ctl = regs.viewport_control;
    for (u32 i = 0; i < AmdGpu::NUM_VIEWPORTS; i++) {
        const auto& vp = regs.viewports[i];
        const auto& vp_d = regs.viewport_depths[i];
        if (vp.xscale == 0) {
            continue;
        }

        const auto zoffset = vp_ctl.zoffset_enable ? vp.zoffset : 0.f;
        const auto zscale = vp_ctl.zscale_enable ? vp.zscale : 1.f;

        vk::Viewport viewport{};

        // https://gitlab.freedesktop.org/mesa/mesa/-/blob/209a0ed/src/amd/vulkan/radv_pipeline_graphics.c#L688-689
        // https://gitlab.freedesktop.org/mesa/mesa/-/blob/209a0ed/src/amd/vulkan/radv_cmd_buffer.c#L3103-3109
        // When the clip space is ranged [-1...1], the zoffset is centered.
        // By reversing the above viewport calculations, we get the following:
        if (regs.clipper_control.clip_space == AmdGpu::ClipSpace::MinusWToW) {
            viewport.minDepth = zoffset - zscale;
            viewport.maxDepth = zoffset + zscale;
        } else {
            viewport.minDepth = zoffset;
            viewport.maxDepth = zoffset + zscale;
        }

        if (!instance.IsDepthRangeUnrestrictedSupported()) {
            // Unrestricted depth range not supported by device. Restrict to valid range.
            viewport.minDepth = std::max(viewport.minDepth, 0.f);
            viewport.maxDepth = std::min(viewport.maxDepth, 1.f);
        }

        if (regs.IsClipDisabled()) {
            // In case if clipping is disabled we patch the shader to convert vertex position
            // from screen space coordinates to NDC by defining a render space as full hardware
            // window range [0..16383, 0..16383] and setting the viewport to its size.
            viewport.x = 0.f;
            viewport.y = 0.f;
            viewport.width = float(std::min<u32>(instance.GetMaxViewportWidth(), 16_KB));
            viewport.height = float(std::min<u32>(instance.GetMaxViewportHeight(), 16_KB));
        } else {
            const auto xoffset = vp_ctl.xoffset_enable ? vp.xoffset : 0.f;
            const auto xscale = vp_ctl.xscale_enable ? vp.xscale : 1.f;
            const auto yoffset = vp_ctl.yoffset_enable ? vp.yoffset : 0.f;
            const auto yscale = vp_ctl.yscale_enable ? vp.yscale : 1.f;

            viewport.x = xoffset - xscale;
            viewport.y = yoffset - yscale;
            viewport.width = xscale * 2.0f;
            viewport.height = yscale * 2.0f;
        }

        viewports.push_back(viewport);

        auto vp_scsr = scsr;
        if (regs.mode_control.vport_scissor_enable) {
            vp_scsr.top_left_x =
                std::max(vp_scsr.top_left_x, s16(regs.viewport_scissors[i].top_left_x));
            vp_scsr.top_left_y =
                std::max(vp_scsr.top_left_y, s16(regs.viewport_scissors[i].top_left_y));
            vp_scsr.bottom_right_x = std::min(AmdGpu::Scissor::Clamp(vp_scsr.bottom_right_x),
                                              regs.viewport_scissors[i].bottom_right_x);
            vp_scsr.bottom_right_y = std::min(AmdGpu::Scissor::Clamp(vp_scsr.bottom_right_y),
                                              regs.viewport_scissors[i].bottom_right_y);
        }
        scissors.push_back({
            .offset = {vp_scsr.top_left_x, vp_scsr.top_left_y},
            .extent = {vp_scsr.GetWidth(), vp_scsr.GetHeight()},
        });
    }

    if (viewports.empty()) {
        // Vulkan requires providing at least one viewport.
        constexpr vk::Viewport empty_viewport = {
            .x = -1.0f,
            .y = -1.0f,
            .width = 1.0f,
            .height = 1.0f,
            .minDepth = 0.0f,
            .maxDepth = 1.0f,
        };
        constexpr vk::Rect2D empty_scissor = {
            .offset = {0, 0},
            .extent = {1, 1},
        };
        viewports.push_back(empty_viewport);
        scissors.push_back(empty_scissor);
    }

    auto& dynamic_state = scheduler.GetDynamicState();
    dynamic_state.SetViewports(viewports);
    dynamic_state.SetScissors(scissors);
}

void Rasterizer::UpdateDepthStencilState() const {
    const auto& regs = liverpool->regs;
    auto& dynamic_state = scheduler.GetDynamicState();

    const auto depth_test_enabled =
        regs.depth_control.depth_enable && regs.depth_buffer.DepthValid();
    dynamic_state.SetDepthTestEnabled(depth_test_enabled);
    if (depth_test_enabled) {
        dynamic_state.SetDepthWriteEnabled(regs.depth_control.depth_write_enable &&
                                           !regs.depth_render_control.depth_clear_enable);
        dynamic_state.SetDepthCompareOp(LiverpoolToVK::CompareOp(regs.depth_control.depth_func));
    }

    const auto depth_bounds_test_enabled = regs.depth_control.depth_bounds_enable;
    dynamic_state.SetDepthBoundsTestEnabled(depth_bounds_test_enabled);
    if (depth_bounds_test_enabled) {
        dynamic_state.SetDepthBounds(regs.depth_bounds_min, regs.depth_bounds_max);
    }

    const auto depth_bias_enabled = regs.polygon_control.NeedsBias();
    dynamic_state.SetDepthBiasEnabled(depth_bias_enabled);
    if (depth_bias_enabled) {
        const bool front = regs.polygon_control.enable_polygon_offset_front;
        dynamic_state.SetDepthBias(
            front ? regs.poly_offset.front_offset : regs.poly_offset.back_offset,
            regs.poly_offset.depth_bias,
            (front ? regs.poly_offset.front_scale : regs.poly_offset.back_scale) / 16.f);
    }

    const auto stencil_test_enabled =
        regs.depth_control.stencil_enable && regs.depth_buffer.StencilValid();
    dynamic_state.SetStencilTestEnabled(stencil_test_enabled);
    if (stencil_test_enabled) {
        const StencilOps front_ops{
            .fail_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_fail_front),
            .pass_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_zpass_front),
            .depth_fail_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_zfail_front),
            .compare_op = LiverpoolToVK::CompareOp(regs.depth_control.stencil_ref_func),
        };
        const StencilOps back_ops = regs.depth_control.backface_enable ? StencilOps{
            .fail_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_fail_back),
            .pass_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_zpass_back),
            .depth_fail_op = LiverpoolToVK::StencilOp(regs.stencil_control.stencil_zfail_back),
            .compare_op = LiverpoolToVK::CompareOp(regs.depth_control.stencil_bf_func),
        } : front_ops;
        dynamic_state.SetStencilOps(front_ops, back_ops);

        const bool stencil_clear = regs.depth_render_control.stencil_clear_enable;
        const auto front = regs.stencil_ref_front;
        const auto back =
            regs.depth_control.backface_enable ? regs.stencil_ref_back : regs.stencil_ref_front;
        dynamic_state.SetStencilReferences(front.stencil_test_val, back.stencil_test_val);
        dynamic_state.SetStencilWriteMasks(!stencil_clear ? front.stencil_write_mask : 0U,
                                           !stencil_clear ? back.stencil_write_mask : 0U);
        dynamic_state.SetStencilCompareMasks(front.stencil_mask, back.stencil_mask);
    }
}

void Rasterizer::UpdatePrimitiveState(const bool is_indexed) const {
    const auto& regs = liverpool->regs;
    auto& dynamic_state = scheduler.GetDynamicState();

    const auto is_list_topology = [](const AmdGpu::PrimitiveType type) {
        const auto topology = LiverpoolToVK::PrimitiveType(type);
        return topology == vk::PrimitiveTopology::ePointList ||
               topology == vk::PrimitiveTopology::eLineList ||
               topology == vk::PrimitiveTopology::eTriangleList ||
               topology == vk::PrimitiveTopology::eLineListWithAdjacency ||
               topology == vk::PrimitiveTopology::eTriangleListWithAdjacency;
    };
    const auto is_patch_list_topology = [](const AmdGpu::PrimitiveType type) {
        // Quad and rect lists are emulated using tessellation.
        return type == AmdGpu::PrimitiveType::PatchPrimitive ||
               type == AmdGpu::PrimitiveType::QuadList || type == AmdGpu::PrimitiveType::RectList;
    };

    const auto prim_restart =
        (regs.enable_primitive_restart & 1) != 0 &&
        (instance.IsListRestartSupported() || !is_list_topology(regs.primitive_type)) &&
        (instance.IsPatchListRestartSupported() || !is_patch_list_topology(regs.primitive_type));
    ASSERT_MSG(!is_indexed || !prim_restart || regs.primitive_restart_index == 0xFFFF ||
                   regs.primitive_restart_index == 0xFFFFFFFF,
               "Primitive restart index other than -1 is not supported yet");

    const auto cull_mode = LiverpoolToVK::IsPrimitiveCulled(regs.primitive_type)
                               ? LiverpoolToVK::CullMode(regs.polygon_control.CullingMode())
                               : vk::CullModeFlagBits::eNone;
    const auto front_face = LiverpoolToVK::FrontFace(regs.polygon_control.front_face);

    dynamic_state.SetPrimitiveRestartEnabled(prim_restart);
    dynamic_state.SetRasterizerDiscardEnabled(regs.clipper_control.dx_rasterization_kill);
    dynamic_state.SetCullMode(cull_mode);
    dynamic_state.SetFrontFace(front_face);
}

void Rasterizer::UpdateRasterizationState() const {
    const auto& regs = liverpool->regs;
    auto& dynamic_state = scheduler.GetDynamicState();
    dynamic_state.SetLineWidth(regs.line_control.Width());
}

void Rasterizer::UpdateColorBlendingState(const GraphicsPipeline* pipeline) const {
    const auto& regs = liverpool->regs;
    auto& dynamic_state = scheduler.GetDynamicState();
    dynamic_state.SetBlendConstants(regs.blend_constants);
    dynamic_state.SetColorWriteMasks(pipeline->GetGraphicsKey().write_masks);
    dynamic_state.SetAttachmentFeedbackLoopEnabled(attachment_feedback_loop);
}

void Rasterizer::ScopeMarkerBegin(const std::string_view& str, bool from_guest) {
    if ((from_guest && !EmulatorSettings.IsVkGuestMarkersEnabled()) ||
        (!from_guest && !EmulatorSettings.IsVkHostMarkersEnabled())) {
        return;
    }
    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.beginDebugUtilsLabelEXT(vk::DebugUtilsLabelEXT{
        .pLabelName = str.data(),
    });
}

void Rasterizer::ScopeMarkerEnd(bool from_guest) {
    if ((from_guest && !EmulatorSettings.IsVkGuestMarkersEnabled()) ||
        (!from_guest && !EmulatorSettings.IsVkHostMarkersEnabled())) {
        return;
    }
    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.endDebugUtilsLabelEXT();
}

void Rasterizer::ScopedMarkerInsert(const std::string_view& str, bool from_guest) {
    if ((from_guest && !EmulatorSettings.IsVkGuestMarkersEnabled()) ||
        (!from_guest && !EmulatorSettings.IsVkHostMarkersEnabled())) {
        return;
    }
    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.insertDebugUtilsLabelEXT(vk::DebugUtilsLabelEXT{
        .pLabelName = str.data(),
    });
}

void Rasterizer::ScopedMarkerInsertColor(const std::string_view& str, const u32 color,
                                         bool from_guest) {
    if ((from_guest && !EmulatorSettings.IsVkGuestMarkersEnabled()) ||
        (!from_guest && !EmulatorSettings.IsVkHostMarkersEnabled())) {
        return;
    }
    const auto cmdbuf = scheduler.CommandBuffer();
    cmdbuf.insertDebugUtilsLabelEXT(vk::DebugUtilsLabelEXT{
        .pLabelName = str.data(),
        .color = std::array<f32, 4>(
            {(f32)((color >> 16) & 0xff) / 255.0f, (f32)((color >> 8) & 0xff) / 255.0f,
             (f32)(color & 0xff) / 255.0f, (f32)((color >> 24) & 0xff) / 255.0f})});
}

} // namespace Vulkan
