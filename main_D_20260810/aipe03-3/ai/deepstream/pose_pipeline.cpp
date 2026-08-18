#include <gst/gst.h>
#include <gstnvdsmeta.h>

#include <chrono>
#include <cstdint>
#include <mutex>
#include <unordered_map>

namespace {
struct StageTimes {
    int64_t rtspReceivedMs = -1;
    int64_t decoderOutputMs = -1;
    int64_t inferenceStartMs = -1;
};

std::mutex gTimesMutex;
std::unordered_map<uint64_t, StageTimes> gTimes;

int64_t nowMs()
{
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

enum class Stage { Rtsp, Decoder, Inference };

GstPadProbeReturn timestampProbe(GstPad*, GstPadProbeInfo* info, gpointer userData)
{
    GstBuffer* buffer = GST_PAD_PROBE_INFO_BUFFER(info);
    if (!buffer || !GST_BUFFER_PTS_IS_VALID(buffer)) return GST_PAD_PROBE_OK;

    uint64_t pts = GST_BUFFER_PTS(buffer);
    const int64_t timestamp = nowMs();
    const Stage stage = *static_cast<Stage*>(userData);
    if (stage == Stage::Inference) {
        NvDsBatchMeta* batchMeta = gst_buffer_get_nvds_batch_meta(buffer);
        if (!batchMeta || !batchMeta->frame_meta_list) return GST_PAD_PROBE_OK;
        auto* frameMeta = static_cast<NvDsFrameMeta*>(batchMeta->frame_meta_list->data);
        if (!frameMeta) return GST_PAD_PROBE_OK;
        pts = frameMeta->buf_pts;
    }
    std::lock_guard<std::mutex> lock(gTimesMutex);
    StageTimes& times = gTimes[pts];
    if (stage == Stage::Rtsp) times.rtspReceivedMs = timestamp;
    else if (stage == Stage::Decoder) times.decoderOutputMs = timestamp;
    else times.inferenceStartMs = timestamp;

    // A worker only needs a few seconds of history. Prevent an interrupted
    // stream or unmatched PTS from growing this registry indefinitely.
    if (gTimes.size() > 2048) gTimes.erase(gTimes.begin());
    return GST_PAD_PROBE_OK;
}

bool addProbe(GstElement* pipeline, const char* elementName, Stage* stage)
{
    GstElement* element = gst_bin_get_by_name(GST_BIN(pipeline), elementName);
    if (!element) return false;
    GstPad* sinkPad = gst_element_get_static_pad(element, "sink");
    gst_object_unref(element);
    if (!sinkPad) return false;
    gst_pad_add_probe(sinkPad, GST_PAD_PROBE_TYPE_BUFFER, timestampProbe, stage, nullptr);
    gst_object_unref(sinkPad);
    return true;
}
}  // namespace

// The nvinferserver custom processor is dlopen()ed into this executable. It
// resolves this symbol with dlsym(RTLD_DEFAULT) and looks up the same frame PTS.
extern "C" bool aipeLookupStageTimestamps(
    uint64_t ptsNs, int64_t* rtspReceivedMs, int64_t* decoderOutputMs,
    int64_t* inferenceStartMs)
{
    std::lock_guard<std::mutex> lock(gTimesMutex);
    auto it = gTimes.find(ptsNs);
    if (it == gTimes.end()) return false;
    if (rtspReceivedMs) *rtspReceivedMs = it->second.rtspReceivedMs;
    if (decoderOutputMs) *decoderOutputMs = it->second.decoderOutputMs;
    if (inferenceStartMs) *inferenceStartMs = it->second.inferenceStartMs;
    gTimes.erase(it);
    return true;
}

int main(int argc, char** argv)
{
    gst_init(&argc, &argv);
    const char* sourceUri = g_getenv("SOURCE_URI");
    if (!sourceUri || !*sourceUri) {
        g_printerr("SOURCE_URI is required\n");
        return 2;
    }

    gchar* description = g_strdup_printf(
        "rtspsrc location=\"%s\" protocols=udp latency=0 buffer-mode=none "
        "udp-buffer-size=65536 drop-on-latency=true ntp-sync=false ! "
        "rtph264depay ! h264parse ! identity name=rtsp_stage ! "
        "nvv4l2decoder low-latency-mode=true disable-dpb=true drop-frame-interval=0 ! "
        "identity name=decoder_stage ! queue leaky=downstream max-size-buffers=1 "
        "max-size-bytes=0 max-size-time=0 ! mux.sink_0 "
        "nvstreammux name=mux batch-size=1 width=640 height=640 enable-padding=true "
        "live-source=true sync-inputs=false batched-push-timeout=15000 ! "
        "identity name=inference_stage ! "
        "nvinferserver config-file-path=/workspace/deepstream/config/config_infer_yolo_pose.txt ! "
        "fakesink sync=false async=false",
        sourceUri);

    GError* error = nullptr;
    GstElement* pipeline = gst_parse_launch(description, &error);
    g_free(description);
    if (!pipeline || error) {
        g_printerr("Pipeline parse failed: %s\n", error ? error->message : "unknown");
        if (error) g_error_free(error);
        if (pipeline) gst_object_unref(pipeline);
        return 1;
    }

    static Stage rtspStage = Stage::Rtsp;
    static Stage decoderStage = Stage::Decoder;
    static Stage inferenceStage = Stage::Inference;
    if (!addProbe(pipeline, "rtsp_stage", &rtspStage) ||
        !addProbe(pipeline, "decoder_stage", &decoderStage) ||
        !addProbe(pipeline, "inference_stage", &inferenceStage)) {
        g_printerr("Failed to attach timestamp probes\n");
        gst_object_unref(pipeline);
        return 1;
    }

    gst_element_set_state(pipeline, GST_STATE_PLAYING);
    GstBus* bus = gst_element_get_bus(pipeline);
    bool running = true;
    while (running) {
        GstMessage* message = gst_bus_timed_pop_filtered(
            bus, GST_CLOCK_TIME_NONE,
            static_cast<GstMessageType>(GST_MESSAGE_ERROR | GST_MESSAGE_EOS));
        if (!message) continue;
        if (GST_MESSAGE_TYPE(message) == GST_MESSAGE_ERROR) {
            GError* messageError = nullptr;
            gchar* debug = nullptr;
            gst_message_parse_error(message, &messageError, &debug);
            g_printerr("Pipeline error: %s\n", messageError->message);
            g_error_free(messageError);
            g_free(debug);
        }
        running = false;
        gst_message_unref(message);
    }

    gst_element_set_state(pipeline, GST_STATE_NULL);
    gst_object_unref(bus);
    gst_object_unref(pipeline);
    return 1;
}
