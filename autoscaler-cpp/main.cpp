#include <iostream>
#include <string>
#include <thread>
#include <chrono>
#include <ctime>
#include <sstream>
#include <algorithm>
#include <curl/curl.h>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// ─────────────────────────────────────────────────────────────
// CONFIGURATION
// These match your actual K8s setup — change if needed
// ─────────────────────────────────────────────────────────────
const std::string PROMETHEUS_URL    = "http://192.168.49.2:30090";
const std::string DISPATCHER_URL    = "http://192.168.49.2:30001";
const std::string K8S_API_URL       = "https://192.168.49.2:8443";
const std::string NAMESPACE         = "default";
const std::string DEPLOYMENT_NAME   = "inference-deployment";

// Scaling parameters — this is your "creative" contribution (slide 17)
const int    MIN_REPLICAS           = 1;
const int    MAX_REPLICAS           = 4;   // limited by 4 CPUs in Minikube
const double SLO_LATENCY_TARGET     = 0.5; // seconds — your hard SLO
const double SCALE_UP_LATENCY       = 0.35;// scale up BEFORE hitting SLO
const double SCALE_DOWN_LATENCY     = 0.15;// scale down when very comfortable
const int    QUEUE_SCALE_UP         = 5;   // scale up if queue > this
const int    SCALE_INTERVAL_SECONDS = 15;  // matches Prometheus scrape interval
const int    COOLDOWN_SECONDS       = 45;  // wait between scaling decisions

// ─────────────────────────────────────────────────────────────
// LIBCURL CALLBACK
// libcurl calls this function each time it receives a chunk of
// HTTP response data. We accumulate chunks into a std::string.
// ─────────────────────────────────────────────────────────────
static size_t WriteCallback(
    void* contents,
    size_t size,
    size_t nmemb,
    std::string* output)
{
    size_t totalSize = size * nmemb;
    output->append(static_cast<char*>(contents), totalSize);
    return totalSize;
}

// ─────────────────────────────────────────────────────────────
// HTTP GET — used to query Prometheus
// ─────────────────────────────────────────────────────────────
std::string httpGet(const std::string& url)
{
    CURL* curl = curl_easy_init();
    std::string response;

    if (!curl) {
        std::cerr << "[ERROR] Failed to init curl\n";
        return "";
    }

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    // Skip SSL verification for Minikube's self-signed cert
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);

    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        std::cerr << "[ERROR] GET " << url
                  << " failed: " << curl_easy_strerror(res) << "\n";
        response = "";
    }

    curl_easy_cleanup(curl);
    return response;
}

// ─────────────────────────────────────────────────────────────
// HTTP POST — used to notify Dispatcher of new replica count
// ─────────────────────────────────────────────────────────────
std::string httpPost(const std::string& url, const std::string& body)
{
    CURL* curl = curl_easy_init();
    std::string response;

    if (!curl) return "";

    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);

    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        std::cerr << "[ERROR] POST " << url
                  << " failed: " << curl_easy_strerror(res) << "\n";
    }

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    return response;
}

// ─────────────────────────────────────────────────────────────
// HTTP PATCH — used to scale the K8s Deployment
// PATCH is a partial update: only sends the fields we want
// to change (replicas), not the entire Deployment spec
// ─────────────────────────────────────────────────────────────
std::string httpPatch(
    const std::string& url,
    const std::string& body,
    const std::string& token)
{
    CURL* curl = curl_easy_init();
    std::string response;

    if (!curl) return "";

    struct curl_slist* headers = nullptr;
    // K8s API requires this Content-Type for PATCH operations
    headers = curl_slist_append(headers,
        "Content-Type: application/merge-patch+json");
    // Bearer token authentication
    std::string authHeader = "Authorization: Bearer " + token;
    headers = curl_slist_append(headers, authHeader.c_str());

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_CUSTOMREQUEST, "PATCH");
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
    curl_easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);

    CURLcode res = curl_easy_perform(curl);
    if (res != CURLE_OK) {
        std::cerr << "[ERROR] PATCH " << url
                  << " failed: " << curl_easy_strerror(res) << "\n";
    }

    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);
    return response;
}

// ─────────────────────────────────────────────────────────────
// QUERY PROMETHEUS
// Sends a PromQL query, parses the JSON response,
// returns the metric value as a double.
// Returns -1.0 on error (no data yet, query failed, etc.)
// ─────────────────────────────────────────────────────────────
double queryPrometheus(const std::string& promql)
{
    // URL-encode the query manually for the key characters
    // (a proper implementation would use curl_easy_escape)
    std::string encoded;
    for (char c : promql) {
        if (c == ' ') encoded += "%20";
        else if (c == '(') encoded += "%28";
        else if (c == ')') encoded += "%29";
        else if (c == '[') encoded += "%5B";
        else if (c == ']') encoded += "%5D";
        else if (c == '{') encoded += "%7B";
        else if (c == '}') encoded += "%7D";
        else if (c == '"') encoded += "%22";
        else if (c == '|') encoded += "%7C";
        else if (c == ',') encoded += "%2C";
        else if (c == '=') encoded += "%3D";
        else if (c == '+') encoded += "%2B";
        else encoded += c;
    }

    std::string url = PROMETHEUS_URL +
                      "/api/v1/query?query=" + encoded;
    std::string response = httpGet(url);

    if (response.empty()) return -1.0;

    try {
        json j = json::parse(response);

        // Response structure:
        // { "status": "success",
        //   "data": { "result": [ { "value": [timestamp, "0.134"] } ] } }
        if (j["status"] != "success") return -1.0;

        auto& results = j["data"]["result"];
        if (results.empty()) return -1.0;

        // value[1] is the actual number, as a STRING (Prometheus quirk)
        std::string valStr = results[0]["value"][1];
        if (valStr == "NaN" || valStr == "nan" || valStr == "+Inf") return -1.0;
        return std::stod(valStr);

    } catch (const std::exception& e) {
        std::cerr << "[ERROR] Failed to parse Prometheus response: "
                  << e.what() << "\n";
        return -1.0;
    }
}

// ─────────────────────────────────────────────────────────────
// GET K8s SERVICE ACCOUNT TOKEN
// When running as a Pod inside K8s, the token is auto-mounted.
// When running outside (on host), we get it from kubectl.
// We're running on the host, so we use kubectl.
// ─────────────────────────────────────────────────────────────
std::string getK8sToken()
{
    FILE* pipe = popen(
        "kubectl create token default --duration=24h 2>/dev/null",
        "r");
    if (!pipe) return "";

    std::string token;
    char buffer[256];
    while (fgets(buffer, sizeof(buffer), pipe) != nullptr) {
        token += buffer;
    }
    pclose(pipe);

    // Remove trailing newline
    if (!token.empty() && token.back() == '\n') {
        token.pop_back();
    }
    return token;
}

// ─────────────────────────────────────────────────────────────
// SCALE K8s DEPLOYMENT
// Sends a PATCH request to the K8s API server to update
// the replica count of our inference deployment.
// ─────────────────────────────────────────────────────────────
bool scaleDeployment(int replicas, const std::string& token)
{
    std::string url = K8S_API_URL +
        "/apis/apps/v1/namespaces/" + NAMESPACE +
        "/deployments/" + DEPLOYMENT_NAME;

    // Minimal JSON patch — only the field we want to change
    json patch = {
        {"spec", {
            {"replicas", replicas}
        }}
    };

    std::string response = httpPatch(url, patch.dump(), token);
    if (response.empty()) return false;

    try {
        json j = json::parse(response);
        // K8s returns the updated Deployment object on success
        // Check the replicas field was actually set
        return j["spec"]["replicas"] == replicas;
    } catch (...) {
        return false;
    }
}

// ─────────────────────────────────────────────────────────────
// NOTIFY DISPATCHER
// After scaling K8s, tell the Dispatcher how many workers
// to maintain. These must stay in sync.
// ─────────────────────────────────────────────────────────────
bool notifyDispatcher(int replicas)
{
    std::string url = DISPATCHER_URL +
        "/scale?target_replicas=" +
        std::to_string(replicas);

    // POST with empty body — target_replicas is a query param
    std::string response = httpPost(url, "{}");
    return !response.empty();
}

// ─────────────────────────────────────────────────────────────
// TIMESTAMP helper for readable logs
// ─────────────────────────────────────────────────────────────
std::string timestamp()
{
    auto now = std::chrono::system_clock::now();
    std::time_t t = std::chrono::system_clock::to_time_t(now);
    char buf[20];
    std::strftime(buf, sizeof(buf), "%H:%M:%S", std::localtime(&t));
    return std::string(buf);
}

// ─────────────────────────────────────────────────────────────
// SCALING LOGIC — the "creative" part (slide 17)
//
// Strategy: proactive + reactive hybrid
//   - React to p99 latency approaching SLO (reactive)
//   - React to queue depth building up (proactive)
//   - Aggressive scale-up, conservative scale-down
//   - Cooldown period prevents oscillation (thrashing)
// ─────────────────────────────────────────────────────────────
int computeDesiredReplicas(
    double p99_latency,
    double queue_depth,
    int current_replicas)
{
    int desired = current_replicas;

    // ── Scale UP conditions ──────────────────────────────────
    if (p99_latency > SLO_LATENCY_TARGET) {
        // SLO already violated — scale up aggressively
        desired = std::min(current_replicas + 2, MAX_REPLICAS);
        std::cout << "  [SCALE UP] SLO violated: p99="
                  << p99_latency << "s\n";
    }
    else if (p99_latency > SCALE_UP_LATENCY) {
        // Approaching SLO — scale up by 1 proactively
        desired = std::min(current_replicas + 1, MAX_REPLICAS);
        std::cout << "  [SCALE UP] Approaching SLO: p99="
                  << p99_latency << "s\n";
    }
    else if (queue_depth > QUEUE_SCALE_UP) {
        // Queue building up — scale up even if latency OK
        desired = std::min(current_replicas + 1, MAX_REPLICAS);
        std::cout << "  [SCALE UP] Queue pressure: depth="
                  << queue_depth << "\n";
    }
    // ── Scale DOWN conditions ────────────────────────────────
    else if (p99_latency < SCALE_DOWN_LATENCY
             && p99_latency > 0
             && queue_depth == 0
             && current_replicas > MIN_REPLICAS) {
        // Very comfortable — scale down conservatively
        desired = std::max(current_replicas - 1, MIN_REPLICAS);
        std::cout << "  [SCALE DOWN] Low load: p99="
                  << p99_latency << "s\n";
    }
    else {
        std::cout << "  [HOLD] No scaling needed\n";
    }

    return desired;
}

// ─────────────────────────────────────────────────────────────
// MAIN LOOP
// ─────────────────────────────────────────────────────────────
int main()
{
    std::cout << "╔══════════════════════════════════════════╗\n";
    std::cout << "║   Elastic ML Inference Autoscaler (C++)  ║\n";
    std::cout << "║   Cloud Computing APL — TU Ilmenau       ║\n";
    std::cout << "╚══════════════════════════════════════════╝\n\n";

    // Initialize libcurl globally (once per process)
    curl_global_init(CURL_GLOBAL_DEFAULT);

    // Get K8s authentication token
    std::cout << "[INIT] Fetching K8s service account token...\n";
    std::string k8sToken = getK8sToken();
    if (k8sToken.empty()) {
        std::cerr << "[FATAL] Could not get K8s token. "
                  << "Is kubectl configured? Is Minikube running?\n";
        return 1;
    }
    std::cout << "[INIT] Token obtained ("
              << k8sToken.size() << " chars)\n";

    int currentReplicas  = 1;
    int lastScaleTime    = 0;  // unix timestamp of last scaling action

    std::cout << "[INIT] Starting autoscaler loop "
              << "(interval=" << SCALE_INTERVAL_SECONDS << "s, "
              << "cooldown=" << COOLDOWN_SECONDS << "s)\n\n";

    // ── Main control loop ────────────────────────────────────
    while (true) {
        auto loopStart = std::chrono::steady_clock::now();

        std::cout << "─────────────────────────────────────────\n";
        std::cout << "[" << timestamp() << "] Autoscaler tick\n";

        // ── Step 1: Query Prometheus ─────────────────────────
        double p99Latency = queryPrometheus(
            "histogram_quantile(0.99, "
            "rate(dispatcher_request_latency_seconds_bucket[2m]))");

        double queueDepth = queryPrometheus(
            "dispatcher_queue_depth");

        std::cout << "  p99_latency : "
                  << (p99Latency < 0 ? "N/A" :
                      std::to_string(p99Latency) + "s") << "\n";
        std::cout << "  queue_depth : "
                  << (queueDepth < 0 ? "N/A" :
                      std::to_string(queueDepth)) << "\n";
        std::cout << "  current_replicas: "
                  << currentReplicas << "\n";

        // ── Step 2: Compute desired replicas ─────────────────
        // Skip scaling if no data yet (system just started)
        if (p99Latency < 0 && queueDepth < 0) {
            std::cout << "  [WAIT] No metrics yet — skipping\n";
        } else {
            // Use 0 for queue depth if unavailable
            double qd = (queueDepth < 0) ? 0 : queueDepth;
            double lat = (p99Latency < 0) ? 0 : p99Latency;

            int desired = computeDesiredReplicas(
                lat, qd, currentReplicas);

            // ── Step 3: Apply cooldown ────────────────────────
            auto now = std::chrono::system_clock::now();
            int nowTs = static_cast<int>(
                std::chrono::system_clock::to_time_t(now));

            bool cooledDown =
                (nowTs - lastScaleTime) >= COOLDOWN_SECONDS;

            if (desired != currentReplicas && cooledDown) {
                std::cout << "  [ACTION] Scaling "
                          << currentReplicas
                          << " → " << desired << " replicas\n";

                // ── Step 4: Scale K8s Deployment ─────────────
                bool k8sOk = scaleDeployment(desired, k8sToken);
                std::cout << "  K8s PATCH: "
                          << (k8sOk ? "OK" : "FAILED") << "\n";

                // ── Step 5: Sync Dispatcher workers ──────────
                bool dispOk = notifyDispatcher(desired);
                std::cout << "  Dispatcher sync: "
                          << (dispOk ? "OK" : "FAILED") << "\n";

                if (k8sOk) {
                    currentReplicas = desired;
                    lastScaleTime   = nowTs;
                }
            } else if (desired != currentReplicas) {
                int remaining = COOLDOWN_SECONDS -
                                (nowTs - lastScaleTime);
                std::cout << "  [COOLDOWN] Want " << desired
                          << " replicas, but cooling down ("
                          << remaining << "s left)\n";
            }
        }

        // ── Sleep until next interval ─────────────────────────
        auto loopEnd = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(loopEnd - loopStart).count();
        int sleepSecs = SCALE_INTERVAL_SECONDS -
                        static_cast<int>(elapsed);

        if (sleepSecs > 0) {
            std::cout << "  [SLEEP] " << sleepSecs
                      << "s until next tick\n";
            std::this_thread::sleep_for(
                std::chrono::seconds(sleepSecs));
        }
    }

    curl_global_cleanup();
    return 0;
}
