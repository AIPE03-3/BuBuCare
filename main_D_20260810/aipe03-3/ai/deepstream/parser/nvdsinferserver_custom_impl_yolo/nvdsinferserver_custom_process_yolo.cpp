/*
 * SPDX-FileCopyrightText: Copyright (c) 2022-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <string.h>
#include <sys/socket.h>
#include <netdb.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <chrono>
#include <dlfcn.h>
#include <cstdlib>
#include <iostream>
#include <map>
#include <mutex>
#include <numeric>
#include <sstream>
#include <string>
#include <unordered_map>

#include "infer_custom_process.h"
#include "nvbufsurface.h"
#include "nvdsmeta.h"

typedef struct _GstBuffer GstBuffer;

/** This is a example how DeepStream Triton plugin(gst-nvinferserver) do
 * custom extra input preprocess and custom postprocess on triton based models.
 */

// enable debug log
#define ENABLE_DEBUG 0

namespace dsis = nvdsinferserver;

#if ENABLE_DEBUG
#define LOG_DEBUG(fmt, ...) fprintf(stdout, "%s:%d" fmt "\n", __FILE__, __LINE__, ##__VA_ARGS__)
#else
#define LOG_DEBUG(fmt, ...)
#endif

#define LOG_ERROR(fmt, ...) fprintf(stderr, "%s:%d" fmt "\n", __FILE__, __LINE__, ##__VA_ARGS__)

#ifndef INFER_ASSERT
#define INFER_ASSERT(expr)                                                     \
    do {                                                                       \
        if (!(expr)) {                                                         \
            fprintf(stderr, "%s:%d ASSERT(%s) \n", __FILE__, __LINE__, #expr); \
            std::abort();                                                      \
        }                                                                      \
    } while (0)
#endif

#define CSTR(str) (str).empty() ? "" : (str).c_str()

// constant values definition
static const std::vector<std::string> kClassLabels = {"person"};
static constexpr float kConfidenceThreshold = 0.45F;
static constexpr float kIouThreshold = 0.70F;
static constexpr float kKeypointThreshold = 0.50F;

struct PoseDetection {
    NvDsInferObjectDetectionInfo box{};
    std::array<float, 17 * 3> keypoints{};
};

static constexpr std::array<std::array<int, 2>, 18> kSkeleton = {{
    {{5, 7}}, {{7, 9}}, {{6, 8}}, {{8, 10}}, {{5, 6}}, {{5, 11}},
    {{6, 12}}, {{11, 12}}, {{11, 13}}, {{13, 15}}, {{12, 14}}, {{14, 16}},
    {{0, 1}}, {{0, 2}}, {{1, 3}}, {{2, 4}}, {{3, 5}}, {{4, 6}},
}};

static float clamp01(float value)
{
    return std::max(0.0F, std::min(1.0F, value));
}

class DetectionUdpSender {
public:
    DetectionUdpSender()
    {
        const char* host = std::getenv("DETECTION_UDP_HOST");
        const char* port = std::getenv("DETECTION_UDP_PORT");
        _baseDeviceId = std::atoi(std::getenv("DETECTION_DEVICE_ID") ?: "301");
        _cameraIdOverride = std::getenv("DETECTION_CAMERA_ID") ?: "";
        _everyN = std::max(1, std::atoi(std::getenv("DETECTION_EVERY_N") ?: "2"));
        _sourceWidth = std::max(1, std::atoi(std::getenv("DETECTION_SOURCE_WIDTH") ?: "1920"));
        _sourceHeight = std::max(1, std::atoi(std::getenv("DETECTION_SOURCE_HEIGHT") ?: "1080"));

        addrinfo hints{};
        hints.ai_family = AF_UNSPEC;
        hints.ai_socktype = SOCK_DGRAM;
        addrinfo* result = nullptr;
        if (getaddrinfo(host ?: "nh-detection-bridge", port ?: "19000", &hints, &result) != 0 ||
            !result) {
            LOG_ERROR("cannot resolve detection UDP destination");
            return;
        }
        _fd = socket(result->ai_family, result->ai_socktype, result->ai_protocol);
        if (_fd >= 0 && result->ai_addrlen <= sizeof(_address)) {
            memcpy(&_address, result->ai_addr, result->ai_addrlen);
            _addressLength = result->ai_addrlen;
        }
        freeaddrinfo(result);
    }

    ~DetectionUdpSender()
    {
        if (_fd >= 0) close(_fd);
    }

    void publish(
        const std::vector<PoseDetection>& poses, uint32_t sourceId,
        uint64_t sourcePtsNs, uint64_t deepstreamFrameNtpNs)
    {
        // A batched pipeline shares this sender across all sources. Counters
        // must therefore be per source; otherwise one camera consumes another
        // camera's throttle turn and all sequence numbers become interleaved.
        auto& calls = _callsBySource[sourceId];
        if (_fd < 0 || (++calls % _everyN) != 0) return;
        auto& sequence = _sequenceBySource[sourceId];
        // In four independent workers every nvstreammux has source_id=0, so
        // DETECTION_DEVICE_ID selects 301/302/303/304. In a future batched
        // worker the env var stays at its default 301 and source_id=0..3 adds
        // the per-stream offset.
        const int deviceId = _baseDeviceId + static_cast<int>(sourceId);
        const std::string cameraId =
            (sourceId == 0 && !_cameraIdOverride.empty())
                ? _cameraIdOverride
                : "Room_" + std::to_string(deviceId);
        const auto aiSentAtMs = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        // pose_pipeline.cpp exports this symbol from the main executable. The
        // custom processor is loaded with dlopen(), so lookup keeps the parser
        // compatible with gst-launch (timestamps remain -1 in that fallback).
        using LookupFn = bool (*)(uint64_t, int64_t*, int64_t*, int64_t*);
        static LookupFn lookup = reinterpret_cast<LookupFn>(
            dlsym(RTLD_DEFAULT, "aipeLookupStageTimestamps"));
        int64_t rtspReceivedAtMs = -1;
        int64_t decoderOutputAtMs = -1;
        int64_t inferenceStartAtMs = -1;
        if (lookup) {
            lookup(sourcePtsNs, &rtspReceivedAtMs, &decoderOutputAtMs, &inferenceStartAtMs);
        }
        const int64_t inferenceEndAtMs = aiSentAtMs;

        // nvstreammux letterboxes the source into the 640x640 inference surface.
        const float gain = std::min(640.0F / _sourceWidth, 640.0F / _sourceHeight);
        const float contentWidth = _sourceWidth * gain;
        const float contentHeight = _sourceHeight * gain;
        const float padX = (640.0F - contentWidth) / 2.0F;
        const float padY = (640.0F - contentHeight) / 2.0F;

        std::ostringstream json;
        json << "{\"device_id\":" << deviceId
             << ",\"camera_id\":\"" << cameraId
             << "\",\"seq\":" << ++sequence
             << ",\"source_pts_ms\":" << (sourcePtsNs / 1000000ULL)
             << ",\"rtsp_received_at_ms\":" << rtspReceivedAtMs
             << ",\"decoder_output_at_ms\":" << decoderOutputAtMs
             << ",\"inference_start_at_ms\":" << inferenceStartAtMs
             << ",\"inference_end_at_ms\":" << inferenceEndAtMs
             << ",\"deepstream_frame_at_ms\":" << (deepstreamFrameNtpNs / 1000000ULL)
             << ",\"ai_sent_at_ms\":" << aiSentAtMs
             << ",\"persons\":[";
        for (size_t i = 0; i < poses.size(); ++i) {
            if (i) json << ',';
            const auto& pose = poses[i];
            const auto& box = pose.box;
            const float x1 = clamp01((box.left - padX) / contentWidth);
            const float y1 = clamp01((box.top - padY) / contentHeight);
            const float x2 = clamp01((box.left + box.width - padX) / contentWidth);
            const float y2 = clamp01((box.top + box.height - padY) / contentHeight);
            json << "{\"bbox\":[" << x1 << ',' << y1 << ',' << x2 << ',' << y2
                 << "],\"conf\":" << box.detectionConfidence
                 << ",\"is_fall\":false,\"track_id\":null,\"kps\":[";
            for (int k = 0; k < 17; ++k) {
                if (k) json << ',';
                if (pose.keypoints[k * 3 + 2] < kKeypointThreshold) {
                    json << "[0,0]";
                } else {
                    const float x = clamp01((pose.keypoints[k * 3] - padX) / contentWidth);
                    const float y = clamp01((pose.keypoints[k * 3 + 1] - padY) / contentHeight);
                    json << '[' << x << ',' << y << ']';
                }
            }
            json << "]}";
        }
        json << "]}";
        const std::string payload = json.str();
        sendto(
            _fd, payload.data(), payload.size(), MSG_DONTWAIT,
            reinterpret_cast<const sockaddr*>(&_address), _addressLength);
    }

private:
    int _fd = -1;
    sockaddr_storage _address{};
    socklen_t _addressLength = 0;
    int _baseDeviceId = 301;
    std::string _cameraIdOverride;
    int _everyN = 2;
    int _sourceWidth = 1920;
    int _sourceHeight = 1080;
    std::unordered_map<uint32_t, uint64_t> _callsBySource;
    std::unordered_map<uint32_t, uint64_t> _sequenceBySource;
};

static float boxIou(
    const PoseDetection& poseA, const PoseDetection& poseB)
{
    const auto& a = poseA.box;
    const auto& b = poseB.box;
    const float left = std::max(a.left, b.left);
    const float top = std::max(a.top, b.top);
    const float right = std::min(a.left + a.width, b.left + b.width);
    const float bottom = std::min(a.top + a.height, b.top + b.height);
    const float intersection = std::max(0.0F, right - left) * std::max(0.0F, bottom - top);
    const float unionArea = a.width * a.height + b.width * b.height - intersection;
    return unionArea > 0.0F ? intersection / unionArea : 0.0F;
}

static std::vector<PoseDetection> nms(std::vector<PoseDetection> boxes)
{
    std::sort(boxes.begin(), boxes.end(), [](const auto& a, const auto& b) {
        return a.box.detectionConfidence > b.box.detectionConfidence;
    });
    std::vector<PoseDetection> kept;
    for (const auto& box : boxes) {
        bool suppressed = false;
        for (const auto& selected : kept) {
            if (boxIou(box, selected) > kIouThreshold) {
                suppressed = true;
                break;
            }
        }
        if (!suppressed) kept.push_back(box);
    }
    return kept;
}

/** Define a function for custom processor for DeepStream Triton plugin(nvinferserver)
 * do custom extra input preprocess and custom postprocess on triton based models.
 * The sysmbol is loaded through
 *   infer_config {
 *     custom_lib {  path: "path/to/custom_impl_process.so" }
 *     extra {
 *       custom_process_funcion: "CreateInferServerCustomProcess"
 *     }}
 */
extern "C" dsis::IInferCustomProcessor* CreateInferServerCustomProcess(
    const char* config, uint32_t configLen);

namespace {
using namespace dsis;

std::string
memType2Str(InferMemType t)
{
    switch (t) {
    case InferMemType::kGpuCuda:
        return "kGpuCuda";
    case InferMemType::kCpu:
        return "kCpu";
    case InferMemType::kCpuCuda:
        return "kCpuPinned";
    default:
        return "Unknown";
    }
}

std::string
dataType2Str(dsis::InferDataType t)
{
    switch (t) {
    case InferDataType::kFp32:
        return "kFp32";
    case InferDataType::kFp16:
        return "kFp16";
    case InferDataType::kInt8:
        return "kInt8";
    case InferDataType::kInt32:
        return "kInt32";
    case InferDataType::kInt16:
        return "kInt16";
    case InferDataType::kUint8:
        return "kUint8";
    case InferDataType::kUint16:
        return "kUint16";
    case InferDataType::kUint32:
        return "kUint32";
    case InferDataType::kFp64:
        return "kFp64";
    case InferDataType::kInt64:
        return "kInt64";
    case InferDataType::kUint64:
        return "kUint64";
    case InferDataType::kString:
        return "kString";
    case InferDataType::kBool:
        return "kBool";
    default:
        return "Unknown";
    }
}

// return buffer description string
std::string
strOfBufDesc(const dsis::InferBufferDescription& desc)
{
    std::stringstream ss;
    ss << "*" << desc.name << "*, shape: ";
    for (uint32_t i = 0; i < desc.dims.numDims; ++i) {
        if (i != 0) {
            ss << "x";
        } else {
            ss << "[";
        }
        ss << desc.dims.d[i];
        if (i == desc.dims.numDims - 1) {
            ss << "]";
        }
    }
    ss << ", dataType:" << dataType2Str(desc.dataType);
    ss << ", memType:" << memType2Str(desc.memType);
    return ss.str();
}

}  // namespace

/** Example of a Custom process instance for deepstream-triton(gst-nvinferserver) plugin
 * It is derived from nvdsinferserver::IInferCustomProcessor
 * If should be loaded through
 * config_triton_inferserver_primary_fasterRCNN.txt:
 *   infer_config {
 *     custom_lib {  path: "path/to/custom_impl_process.so" }
 *     extra {
 *       custom_process_funcion: "CreateInferServerCustomProcess"
 *     }
 *   }
 */
class NvInferServerCustomProcess : public dsis::IInferCustomProcessor {
private:
    std::map<uint64_t, std::vector<float>> _streamFeedback;
    std::mutex _streamMutex;

public:
    ~NvInferServerCustomProcess() override = default;
    /** override function
     * Specifies supported extraInputs memtype in extraInputProcess()
     */
    void supportInputMemType(dsis::InferMemType& type) override { type = dsis::InferMemType::kCpu; }

    /** override function
     * check whether custom loop process needed.
     * If return True, extraInputProcess() and inferenceDone() runs in order per stream_ids
     * This is usually for LSTM loop purpose. FasterRCNN does not need it.
     * The code for requireInferLoop() conditions just sample when user has
     * a LSTM-like Loop model and requires loop custom processing.
     * */
    bool requireInferLoop() const override { return false; }

    /**
     * override function
     * Do custom processing on extra inputs.
     * @primaryInput is already preprocessed. DO NOT update it again.
     * @extraInputs, do custom processing and fill all data according the tensor shape
     * @options, it has most of the common Deepstream metadata along with primary data.
     *           e.g. NvDsBatchMeta, NvDsObjectMeta, NvDsFrameMeta, stream ids...
     *           see infer_ioptions.h to see all the potential key name and structures
     *           in the key-value table.
     */
    NvDsInferStatus extraInputProcess(
        const std::vector<dsis::IBatchBuffer*>&
            primaryInputs,  // primary tensor(image) has been processed
        std::vector<dsis::IBatchBuffer*>& extraInputs, const dsis::IOptions* options) override
    {
        INFER_ASSERT(primaryInputs.size() > 0);
        // YOLO11 Pose has only the primary "images" tensor. DeepStream still
        // invokes this hook when a custom processor is configured, so an empty
        // extra-input list is a valid no-op rather than an error.
        if (extraInputs.empty()) {
            return NVDSINFER_SUCCESS;
        }
        INFER_ASSERT(extraInputs.size() == 1);
        // primary input tensor: input_1 [batch, channel, height, width]
        dsis::InferBufferDescription input0Desc = primaryInputs[0]->getBufDesc();
        // extra input tensor: image_shape [batch, 2]
        dsis::InferBufferDescription extra1Desc = extraInputs[0]->getBufDesc();
        INFER_ASSERT(extra1Desc.dataType == dsis::InferDataType::kFp32);
        INFER_ASSERT(extra1Desc.elementSize == sizeof(float));  // bytes per element

        INFER_ASSERT(!strOfBufDesc(input0Desc).empty());
        LOG_DEBUG("extraInputProcess: primary input %s", strOfBufDesc(input0Desc).c_str());
        LOG_DEBUG("extraInputProcess: extra input %s", strOfBufDesc(extra1Desc).c_str());

        // batch size must be get from primary input tensor.
        // extra inputs 'image_shape' does not have a batch size in this specific model
        int batchSize = input0Desc.dims.d[0];
        INFER_ASSERT(extra1Desc.dims.numDims == 2 && extra1Desc.dims.d[0] == batchSize);
        INFER_ASSERT(batchSize >= 1);
        if (!options) {
            LOG_ERROR("custom process does not receive IOptions");
            return NVDSINFER_CUSTOM_LIB_FAILED;
        }

        NvDsBatchMeta* batchMeta = nullptr;
        std::vector<NvDsFrameMeta*> frameMetaList;
        NvBufSurface* bufSurf = nullptr;
        std::vector<NvBufSurfaceParams*> surfParamsList;
        std::vector<uint64_t> streamIds;
        int64_t unique_id = 0;
        INFER_ASSERT(options->getValueArray(OPTION_NVDS_SREAM_IDS, streamIds) == NVDSINFER_SUCCESS);
        INFER_ASSERT(streamIds.size() == (uint32_t)batchSize);

        // get NvBufSurface
        if (options->hasValue(OPTION_NVDS_BUF_SURFACE)) {
            INFER_ASSERT(options->getObj(OPTION_NVDS_BUF_SURFACE, bufSurf) == NVDSINFER_SUCCESS);
        }
        INFER_ASSERT(bufSurf);

        // get NvDsBatchMeta
        if (options->hasValue(OPTION_NVDS_BATCH_META)) {
            INFER_ASSERT(options->getObj(OPTION_NVDS_BATCH_META, batchMeta) == NVDSINFER_SUCCESS);
        }
        INFER_ASSERT(batchMeta);

        // get all frame meta list into vector<NvDsFrameMeta*>
        if (options->hasValue(OPTION_NVDS_FRAME_META_LIST)) {
            INFER_ASSERT(
                options->getValueArray(OPTION_NVDS_FRAME_META_LIST, frameMetaList) ==
                NVDSINFER_SUCCESS);
        }

        // get unique_id
        if (options->hasValue(OPTION_NVDS_UNIQUE_ID)) {
            INFER_ASSERT(options->getInt(OPTION_NVDS_UNIQUE_ID, unique_id) == NVDSINFER_SUCCESS);
        }

        // get all surface params list into vector<NvBufSurfaceParams*>
        if (options->hasValue(OPTION_NVDS_BUF_SURFACE_PARAMS_LIST)) {
            INFER_ASSERT(
                options->getValueArray(OPTION_NVDS_BUF_SURFACE_PARAMS_LIST, surfParamsList) ==
                NVDSINFER_SUCCESS);
        }

        // fill extra input tensor "image_shape[-1,2]"
        float* image_shape = (float*)extraInputs[0]->getBufPtr(0);

        for (int iBatch = 0; iBatch < batchSize; ++iBatch) {
            image_shape[iBatch * 2 + 1] = (float)surfParamsList[iBatch]->width;
            image_shape[iBatch * 2] = (float)surfParamsList[iBatch]->height;
        }
        return NVDSINFER_SUCCESS;
    }

    /** override function
     * Custom processing for inferenced output tensors.
     * output memory types is controlled by gst-nvinferserver config file
     *     config_triton_inferserver_primary_fasterRCNN.txt:
     *       infer_config {
     *         backend {  output_mem_type: MEMORY_TYPE_CPU }
     *     }
     * User can even attach parsed metadata into GstBuffer from this function
     */
    NvDsInferStatus inferenceDone(
        const dsis::IBatchArray* outputs, const dsis::IOptions* inOptions) override
    {
        std::vector<uint64_t> streamIds;
        INFER_ASSERT(
            inOptions->getValueArray(OPTION_NVDS_SREAM_IDS, streamIds) == NVDSINFER_SUCCESS);
        INFER_ASSERT(!streamIds.empty());
        uint32_t batchSize = streamIds.size();
        std::vector<std::vector<PoseDetection>> parsedPoses(batchSize);

        // YOLO11 Pose exports one tensor shaped [batch, 56, candidates].
        std::unordered_map<std::string, const dsis::IBatchBuffer*> tensors;
        for (uint32_t iTensor = 0; iTensor < outputs->getSize(); ++iTensor) {
            const dsis::IBatchBuffer* outTensor = outputs->getBuffer(iTensor);
            INFER_ASSERT(outTensor);
            auto desc = outTensor->getBufDesc();
            LOG_DEBUG("out tensor: %s, desc: %s \n", CSTR(desc.name), strOfBufDesc(desc).c_str());
            tensors.emplace(desc.name, outTensor);
        }

        auto output = tensors["output0"];
        INFER_ASSERT(output);
        const auto desc = output->getBufDesc();
        INFER_ASSERT(desc.dataType == dsis::InferDataType::kFp32);
        INFER_ASSERT(desc.dims.numDims == 3);
        INFER_ASSERT(desc.dims.d[0] == static_cast<int>(batchSize));
        INFER_ASSERT(desc.dims.d[1] == 56);
        const int candidates = desc.dims.d[2];
        const int channels = desc.dims.d[1];
        const float* raw = static_cast<const float*>(output->getBufPtr(0));

        for (uint32_t batchId = 0; batchId < batchSize; ++batchId) {
            const float* batch = raw + batchId * channels * candidates;
            std::vector<PoseDetection> candidatesForNms;
            for (int i = 0; i < candidates; ++i) {
                const float confidence = batch[4 * candidates + i];
                if (!std::isfinite(confidence) || confidence < kConfidenceThreshold) continue;
                const float cx = batch[i];
                const float cy = batch[candidates + i];
                const float width = batch[2 * candidates + i];
                const float height = batch[3 * candidates + i];
                if (width <= 0.0F || height <= 0.0F) continue;

                PoseDetection pose{};
                auto& obj = pose.box;
                obj.classId = 0;
                obj.left = std::max(0.0F, cx - width / 2.0F);
                obj.top = std::max(0.0F, cy - height / 2.0F);
                obj.width = width;
                obj.height = height;
                obj.detectionConfidence = confidence;
                for (int k = 0; k < 17; ++k) {
                    pose.keypoints[k * 3] = batch[(5 + k * 3) * candidates + i];
                    pose.keypoints[k * 3 + 1] = batch[(6 + k * 3) * candidates + i];
                    pose.keypoints[k * 3 + 2] = batch[(7 + k * 3) * candidates + i];
                }
                candidatesForNms.push_back(pose);
            }
            parsedPoses[batchId] = nms(std::move(candidatesForNms));
        }

        for (uint32_t iBatch = 0; iBatch < batchSize; ++iBatch) {
            INFER_ASSERT(attachObjMeta(inOptions, parsedPoses[iBatch], iBatch) == NVDSINFER_SUCCESS);
        }

        // Map every result in the inference batch back to its nvstreammux
        // source. mux.sink_0..3 correspond to devices 301..304.
        std::vector<NvDsFrameMeta*> frameMetaList;
        INFER_ASSERT(
            inOptions->getValueArray(OPTION_NVDS_FRAME_META_LIST, frameMetaList) ==
            NVDSINFER_SUCCESS);
        INFER_ASSERT(frameMetaList.size() == parsedPoses.size());

        // UDP is non-blocking; if the bridge is down or overloaded this frame
        // is dropped without slowing inference.
        static DetectionUdpSender udpSender;
        for (uint32_t iBatch = 0; iBatch < batchSize; ++iBatch) {
            INFER_ASSERT(frameMetaList[iBatch]);
            const uint32_t sourceId = frameMetaList[iBatch]->source_id;
            udpSender.publish(
                parsedPoses[iBatch], sourceId,
                frameMetaList[iBatch]->buf_pts,
                frameMetaList[iBatch]->ntp_timestamp);
        }

        return NVDSINFER_SUCCESS;
    }

    /** override function
     * Receiving errors if anything wrong inside lowlevel lib
     */
    void notifyError(NvDsInferStatus s) override
    {
        std::unique_lock<std::mutex> locker(_streamMutex);
        _streamFeedback.clear();
    }

private:
    /** function for loop processing only. not requried for fasterRCNN
     */
    NvDsInferStatus feedbackStreamInput(
        const dsis::IBatchArray* outputs, const dsis::IOptions* inOptions);

    /**
     * attach bounding boxes into NvDsBatchMeta and NvDsFrameMeta
     */
    NvDsInferStatus attachObjMeta(
        const dsis::IOptions* inOptions, const std::vector<PoseDetection>& poses,
        uint32_t batchIdx);
};

/** Implementation to Create a custom processor for DeepStream Triton
 * plugin(nvinferserver) to do custom extra input preprocess and custom
 * postprocess on triton based models.
 */
extern "C" {
dsis::IInferCustomProcessor*
CreateInferServerCustomProcess(const char* config, uint32_t configLen)
{
    return new NvInferServerCustomProcess();
}
}

/**
 * attach bounding boxes into NvDsBatchMeta and NvDsFrameMeta
 */
NvDsInferStatus
NvInferServerCustomProcess::attachObjMeta(
    const dsis::IOptions* inOptions, const std::vector<PoseDetection>& poses,
    uint32_t batchIdx)
{
    INFER_ASSERT(inOptions);
    GstBuffer* gstBuf = nullptr;
    NvDsBatchMeta* batchMeta = nullptr;
    std::vector<NvDsFrameMeta*> frameMetaList;
    NvBufSurface* bufSurf = nullptr;
    std::vector<NvBufSurfaceParams*> surfParamsList;
    int64_t unique_id = 0;

    // get GstBuffer
    if (inOptions->hasValue(OPTION_NVDS_GST_BUFFER)) {
        INFER_ASSERT(inOptions->getObj(OPTION_NVDS_GST_BUFFER, gstBuf) == NVDSINFER_SUCCESS);
    }
    INFER_ASSERT(gstBuf);

    // get NvBufSurface
    if (inOptions->hasValue(OPTION_NVDS_BUF_SURFACE)) {
        INFER_ASSERT(inOptions->getObj(OPTION_NVDS_BUF_SURFACE, bufSurf) == NVDSINFER_SUCCESS);
    }
    INFER_ASSERT(bufSurf);

    // get NvDsBatchMeta
    if (inOptions->hasValue(OPTION_NVDS_BATCH_META)) {
        INFER_ASSERT(inOptions->getObj(OPTION_NVDS_BATCH_META, batchMeta) == NVDSINFER_SUCCESS);
    }
    INFER_ASSERT(batchMeta);

    // get all frame meta list into vector<NvDsFrameMeta*>
    if (inOptions->hasValue(OPTION_NVDS_FRAME_META_LIST)) {
        INFER_ASSERT(
            inOptions->getValueArray(OPTION_NVDS_FRAME_META_LIST, frameMetaList) ==
            NVDSINFER_SUCCESS);
    }
    INFER_ASSERT(batchIdx < frameMetaList.size());  // batchsize

    // get unique_id
    if (inOptions->hasValue(OPTION_NVDS_UNIQUE_ID)) {
        INFER_ASSERT(inOptions->getInt(OPTION_NVDS_UNIQUE_ID, unique_id) == NVDSINFER_SUCCESS);
    }

    // get all surface params list into vector<NvBufSurfaceParams*>
    if (inOptions->hasValue(OPTION_NVDS_BUF_SURFACE_PARAMS_LIST)) {
        INFER_ASSERT(
            inOptions->getValueArray(OPTION_NVDS_BUF_SURFACE_PARAMS_LIST, surfParamsList) ==
            NVDSINFER_SUCCESS);
    }
    INFER_ASSERT(batchIdx < surfParamsList.size());  // batchsize

    // attach object's boundingbox
    for (const auto& pose : poses) {
        const auto& obj = pose.box;
        NvDsObjectMeta* objMeta = nvds_acquire_obj_meta_from_pool(batchMeta);
        objMeta->unique_component_id = unique_id;
        objMeta->confidence = obj.detectionConfidence;

        /* This is an untracked object. Set tracking_id to -1. */
        objMeta->object_id = UNTRACKED_OBJECT_ID;
        objMeta->class_id = obj.classId;

        NvOSD_RectParams& rect_params = objMeta->rect_params;
        NvOSD_TextParams& text_params = objMeta->text_params;

        rect_params.left = obj.left;
        rect_params.top = obj.top;
        rect_params.width = obj.width;
        rect_params.height = obj.height;

        /* Border of width 3. */
        rect_params.border_width = 3;
        rect_params.has_bg_color = 0;
        rect_params.border_color = (NvOSD_ColorParams){1, 0, 0, 1};

        /* display_text requires heap allocated memory. */
        if (obj.classId < kClassLabels.size()) {
            text_params.display_text = g_strdup(kClassLabels[obj.classId].c_str());
            strncpy(objMeta->obj_label, kClassLabels[obj.classId].c_str(), MAX_LABEL_SIZE - 1);
            objMeta->obj_label[MAX_LABEL_SIZE - 1] = 0;
        }
        /* Display text above the left top corner of the object. */
        text_params.x_offset = rect_params.left;
        text_params.y_offset = rect_params.top - 10;
        /* Set black background for the text. */
        text_params.set_bg_clr = 1;
        text_params.text_bg_clr = (NvOSD_ColorParams){0, 0, 0, 1};
        /* Font face, size and color. */
        text_params.font_params.font_name = (gchar*)"Serif";
        text_params.font_params.font_size = 11;
        text_params.font_params.font_color = (NvOSD_ColorParams){1, 1, 1, 1};

        nvds_acquire_meta_lock(batchMeta);
        nvds_add_obj_meta_to_frame(frameMetaList[batchIdx], objMeta, NULL);
        frameMetaList[batchIdx]->bInferDone = TRUE;
        nvds_release_meta_lock(batchMeta);
    }

    // Draw COCO keypoints and skeleton using display metadata. A display-meta
    // block has a fixed element capacity, so allocate additional blocks as needed.
    NvDsFrameMeta* frameMeta = frameMetaList[batchIdx];
    for (const auto& pose : poses) {
        for (int start = 0; start < 17; start += MAX_ELEMENTS_IN_DISPLAY_META) {
            NvDsDisplayMeta* displayMeta = nvds_acquire_display_meta_from_pool(batchMeta);
            displayMeta->num_circles = 0;
            for (int k = start; k < std::min(17, start + MAX_ELEMENTS_IN_DISPLAY_META); ++k) {
                const float visibility = pose.keypoints[k * 3 + 2];
                if (!std::isfinite(visibility) || visibility < kKeypointThreshold) continue;
                auto& circle = displayMeta->circle_params[displayMeta->num_circles++];
                circle.xc = static_cast<guint>(std::max(0.0F, pose.keypoints[k * 3]));
                circle.yc = static_cast<guint>(std::max(0.0F, pose.keypoints[k * 3 + 1]));
                circle.radius = 4;
                circle.circle_color = (NvOSD_ColorParams){0, 1, 0, 1};
                circle.has_bg_color = 1;
                circle.bg_color = (NvOSD_ColorParams){0, 1, 0, 1};
            }
            if (displayMeta->num_circles > 0) {
                nvds_acquire_meta_lock(batchMeta);
                nvds_add_display_meta_to_frame(frameMeta, displayMeta);
                nvds_release_meta_lock(batchMeta);
            }
        }

        for (int start = 0; start < static_cast<int>(kSkeleton.size());
             start += MAX_ELEMENTS_IN_DISPLAY_META) {
            NvDsDisplayMeta* displayMeta = nvds_acquire_display_meta_from_pool(batchMeta);
            displayMeta->num_lines = 0;
            const int end = std::min(
                static_cast<int>(kSkeleton.size()), start + MAX_ELEMENTS_IN_DISPLAY_META);
            for (int edgeIndex = start; edgeIndex < end; ++edgeIndex) {
                const int a = kSkeleton[edgeIndex][0];
                const int b = kSkeleton[edgeIndex][1];
                if (pose.keypoints[a * 3 + 2] < kKeypointThreshold ||
                    pose.keypoints[b * 3 + 2] < kKeypointThreshold) {
                    continue;
                }
                auto& line = displayMeta->line_params[displayMeta->num_lines++];
                line.x1 = static_cast<guint>(std::max(0.0F, pose.keypoints[a * 3]));
                line.y1 = static_cast<guint>(std::max(0.0F, pose.keypoints[a * 3 + 1]));
                line.x2 = static_cast<guint>(std::max(0.0F, pose.keypoints[b * 3]));
                line.y2 = static_cast<guint>(std::max(0.0F, pose.keypoints[b * 3 + 1]));
                line.line_width = 3;
                line.line_color = (NvOSD_ColorParams){0, 1, 1, 1};
            }
            if (displayMeta->num_lines > 0) {
                nvds_acquire_meta_lock(batchMeta);
                nvds_add_display_meta_to_frame(frameMeta, displayMeta);
                nvds_release_meta_lock(batchMeta);
            }
        }
    }

    return NVDSINFER_SUCCESS;
}
