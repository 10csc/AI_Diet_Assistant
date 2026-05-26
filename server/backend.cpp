// [DEPRECATED] 此 C++ 后端已由 server/run_server.py (Flask) 替代。
// 保留此文件用于参考，新功能请优先在 Flask 后端中实现。
// 移除计划：下一大版本迭代时清理。

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <vector>

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <winhttp.h>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "winhttp.lib")

namespace {

const int BUFFER_SIZE = 16384;

struct SimpleConfig {
    std::map<std::string, std::string> settings;
};

struct ChatRequest {
    std::string user_input;
    std::string personal_info;
    std::string weather;
    std::string primary_model_id;
    std::string secondary_model_id;
    std::string primary_api_key;
    std::string secondary_api_key;
    std::string conversation_id;
    std::string conversation_title;
    std::string conversation_context;
    std::string recipe_profile;
    bool use_secondary = false;
};

struct RuntimeConfig {
    int port;
    std::string static_dir;
    std::string python_script;
    std::string config_path;
    std::string logs_dir;
    std::string weather_city_csv;
};

bool read_file(const std::string& path, std::string& content);
bool write_file(const std::string& path, const std::string& content);
bool extract_json_string(const std::string& body, const std::string& key, std::string& value);
std::string json_escape(const std::string& input);
std::string fetch_weather_proxy_json(const std::string& district_id, const std::string& ak);

std::string trim(const std::string& value) {
    size_t start = value.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) {
        return "";
    }

    size_t end = value.find_last_not_of(" \t\r\n");
    return value.substr(start, end - start + 1);
}

std::string dirname(const std::string& path) {
    const size_t pos = path.find_last_of("\\/");
    if (pos == std::string::npos) {
        return "";
    }
    return path.substr(0, pos);
}

std::string join_path(const std::string& base, const std::string& child) {
    if (base.empty()) {
        return child;
    }
    if (child.empty()) {
        return base;
    }
    if (child.size() > 1 && child[1] == ':') {
        return child;
    }
    if (child[0] == '\\' || child[0] == '/') {
        return child;
    }
    if (base[base.size() - 1] == '\\' || base[base.size() - 1] == '/') {
        return base + child;
    }
    return base + "\\" + child;
}

std::string normalize_separators(std::string path) {
    std::replace(path.begin(), path.end(), '/', '\\');
    return path;
}

bool path_exists(const std::string& path) {
    const DWORD attrs = GetFileAttributesA(path.c_str());
    return attrs != INVALID_FILE_ATTRIBUTES;
}

bool is_directory_path(const std::string& path) {
    const DWORD attrs = GetFileAttributesA(path.c_str());
    return attrs != INVALID_FILE_ATTRIBUTES && (attrs & FILE_ATTRIBUTE_DIRECTORY) != 0;
}

std::string get_current_directory_path() {
    char buffer[MAX_PATH];
    const DWORD size = GetCurrentDirectoryA(MAX_PATH, buffer);
    if (size == 0 || size > MAX_PATH) {
        return "";
    }
    return std::string(buffer, size);
}

std::string get_executable_path() {
    char buffer[MAX_PATH];
    const DWORD size = GetModuleFileNameA(NULL, buffer, MAX_PATH);
    if (size == 0 || size == MAX_PATH) {
        return "";
    }
    return std::string(buffer, size);
}

std::vector<std::string> build_search_roots() {
    std::vector<std::string> roots;

    const std::string cwd = get_current_directory_path();
    if (!cwd.empty()) {
        roots.push_back(cwd);
    }

    std::string exe_dir = dirname(get_executable_path());
    while (!exe_dir.empty()) {
        if (std::find(roots.begin(), roots.end(), exe_dir) == roots.end()) {
            roots.push_back(exe_dir);
        }
        const std::string parent = dirname(exe_dir);
        if (parent.empty() || parent == exe_dir) {
            break;
        }
        exe_dir = parent;
    }

    return roots;
}

std::string resolve_existing_path(const std::vector<std::string>& roots, const std::string& candidate) {
    if (candidate.empty()) {
        return "";
    }

    std::string normalized = normalize_separators(candidate);
    if ((normalized.size() > 1 && normalized[1] == ':') || path_exists(normalized)) {
        if (path_exists(normalized)) {
            return normalized;
        }
    }

    for (size_t i = 0; i < roots.size(); ++i) {
        const std::string combined = normalize_separators(join_path(roots[i], candidate));
        if (path_exists(combined)) {
            return combined;
        }
    }

    return normalized;
}

bool extract_json_number(const std::string& body, const std::string& key, int& value) {
    const std::string token = "\"" + key + "\"";
    size_t key_pos = body.find(token);
    if (key_pos == std::string::npos) {
        return false;
    }

    size_t colon_pos = body.find(':', key_pos + token.size());
    if (colon_pos == std::string::npos) {
        return false;
    }

    size_t pos = colon_pos + 1;
    while (pos < body.size() && std::isspace(static_cast<unsigned char>(body[pos]))) {
        ++pos;
    }

    size_t end = pos;
    while (end < body.size() && std::isdigit(static_cast<unsigned char>(body[end]))) {
        ++end;
    }

    if (end == pos) {
        return false;
    }

    value = std::atoi(body.substr(pos, end - pos).c_str());
    return true;
}

SimpleConfig load_config_text(const std::string& path) {
    SimpleConfig config;

    std::ifstream file(path.c_str());
    if (!file.is_open()) {
        return config;
    }

    std::string line;
    while (std::getline(file, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#') {
            continue;
        }

        size_t pos = line.find('=');
        if (pos == std::string::npos) {
            continue;
        }

        std::string key = trim(line.substr(0, pos));
        std::string value = trim(line.substr(pos + 1));
        if (!key.empty()) {
            config.settings[key] = value;
        }
    }

    return config;
}

bool load_config_json(const std::string& path, SimpleConfig& config) {
    std::string content;
    if (!read_file(path, content)) {
        return false;
    }

    std::string static_dir;
    std::string python_script;
    int port = 0;

    extract_json_string(content, "static_dir", static_dir);
    extract_json_string(content, "python_script", python_script);
    extract_json_number(content, "port", port);

    if (port > 0) {
        config.settings["port"] = std::to_string(port);
    }
    if (!static_dir.empty()) {
        config.settings["static_dir"] = static_dir;
    }
    if (!python_script.empty()) {
        config.settings["python_script"] = python_script;
    }

    return !config.settings.empty();
}

RuntimeConfig load_runtime_config() {
    RuntimeConfig runtime;
    runtime.port = 8080;
    runtime.static_dir = "./frontend";
    runtime.python_script = "../ai_core/main.py";
    runtime.config_path = "Config.json";
    runtime.logs_dir = "../ai_core/logs";
    runtime.weather_city_csv = "../weather_district_id.csv";

    const std::vector<std::string> roots = build_search_roots();
    SimpleConfig parsed;

    const std::string json_path = resolve_existing_path(roots, "Config.json");
    runtime.config_path = json_path;
    if (path_exists(json_path) && load_config_json(json_path, parsed)) {
        std::cout << "[INFO] Loaded config from " << json_path << std::endl;
    } else {
        const std::string text_path = resolve_existing_path(roots, "config.txt");
        parsed = load_config_text(text_path);
        if (!parsed.settings.empty()) {
            std::cout << "[INFO] Loaded config from " << text_path << std::endl;
        } else {
            std::cerr << "[WARNING] Config.json and config.txt were not found, using default settings" << std::endl;
        }
    }

    if (parsed.settings.find("port") != parsed.settings.end()) {
        runtime.port = std::atoi(parsed.settings["port"].c_str());
    }
    if (parsed.settings.find("static_dir") != parsed.settings.end()) {
        runtime.static_dir = resolve_existing_path(roots, parsed.settings["static_dir"]);
    } else {
        runtime.static_dir = resolve_existing_path(roots, runtime.static_dir);
    }
    if (parsed.settings.find("python_script") != parsed.settings.end()) {
        runtime.python_script = resolve_existing_path(roots, parsed.settings["python_script"]);
    } else {
        runtime.python_script = resolve_existing_path(roots, runtime.python_script);
    }

    runtime.logs_dir = normalize_separators(join_path(dirname(runtime.python_script), "logs"));
    runtime.weather_city_csv = resolve_existing_path(roots, "weather_district_id.csv");

    return runtime;
}

bool init_winsock() {
    WSADATA wsaData;
    return WSAStartup(MAKEWORD(2, 2), &wsaData) == 0;
}

void cleanup_winsock() {
    WSACleanup();
}

SOCKET create_server_socket(int port) {
    SOCKET server_socket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (server_socket == INVALID_SOCKET) {
        return INVALID_SOCKET;
    }

    int opt = 1;
    setsockopt(server_socket, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<char*>(&opt), sizeof(opt));

    sockaddr_in server_addr;
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(static_cast<u_short>(port));
    server_addr.sin_addr.s_addr = INADDR_ANY;

    if (bind(server_socket, reinterpret_cast<sockaddr*>(&server_addr), sizeof(server_addr)) == SOCKET_ERROR) {
        closesocket(server_socket);
        return INVALID_SOCKET;
    }

    if (listen(server_socket, 10) == SOCKET_ERROR) {
        closesocket(server_socket);
        return INVALID_SOCKET;
    }

    return server_socket;
}

std::string get_request_body(const std::string& raw_request) {
    size_t body_start = raw_request.find("\r\n\r\n");
    if (body_start == std::string::npos) {
        return "";
    }
    return raw_request.substr(body_start + 4);
}

std::string get_request_line_part(const std::string& request_line, size_t index) {
    std::istringstream iss(request_line);
    std::string part;
    for (size_t i = 0; i <= index; ++i) {
        if (!(iss >> part)) {
            return "";
        }
    }
    return part;
}

int get_content_length(const std::string& raw_request) {
    const std::string header = "Content-Length:";
    size_t pos = raw_request.find(header);
    if (pos == std::string::npos) {
        return 0;
    }

    pos += header.size();
    while (pos < raw_request.size() && std::isspace(static_cast<unsigned char>(raw_request[pos]))) {
        ++pos;
    }

    size_t end = pos;
    while (end < raw_request.size() && std::isdigit(static_cast<unsigned char>(raw_request[end]))) {
        ++end;
    }

    if (end == pos) {
        return 0;
    }

    return std::atoi(raw_request.substr(pos, end - pos).c_str());
}

bool receive_http_request(SOCKET client_socket, std::string& raw_request) {
    raw_request.clear();
    size_t header_end = std::string::npos;
    int content_length = 0;

    while (true) {
        char buffer[BUFFER_SIZE];
        const int bytes_received = recv(client_socket, buffer, BUFFER_SIZE - 1, 0);
        if (bytes_received <= 0) {
            break;
        }

        raw_request.append(buffer, bytes_received);

        if (header_end == std::string::npos) {
            header_end = raw_request.find("\r\n\r\n");
            if (header_end != std::string::npos) {
                content_length = get_content_length(raw_request);
                if (content_length <= 0) {
                    return true;
                }
            }
        }

        if (header_end != std::string::npos) {
            const size_t body_start = header_end + 4;
            if (raw_request.size() >= body_start + static_cast<size_t>(content_length)) {
                return true;
            }
        }

        if (raw_request.size() > 1024 * 1024) {
            return false;
        }
    }

    return !raw_request.empty();
}

std::string url_decode(const std::string& value) {
    std::string decoded;
    decoded.reserve(value.size());

    for (size_t i = 0; i < value.size(); ++i) {
        if (value[i] == '%' && i + 2 < value.size()) {
            const std::string hex = value.substr(i + 1, 2);
            char ch = static_cast<char>(std::strtol(hex.c_str(), NULL, 16));
            decoded.push_back(ch);
            i += 2;
        } else if (value[i] == '+') {
            decoded.push_back(' ');
        } else {
            decoded.push_back(value[i]);
        }
    }

    return decoded;
}

std::string get_request_path_only(const std::string& path_with_query) {
    const size_t pos = path_with_query.find('?');
    if (pos == std::string::npos) {
        return path_with_query;
    }
    return path_with_query.substr(0, pos);
}

std::string get_query_param(const std::string& path_with_query, const std::string& key) {
    const size_t pos = path_with_query.find('?');
    if (pos == std::string::npos || pos + 1 >= path_with_query.size()) {
        return "";
    }

    std::istringstream iss(path_with_query.substr(pos + 1));
    std::string item;
    while (std::getline(iss, item, '&')) {
        const size_t eq_pos = item.find('=');
        if (eq_pos == std::string::npos) {
            continue;
        }
        if (item.substr(0, eq_pos) == key) {
            return url_decode(item.substr(eq_pos + 1));
        }
    }

    return "";
}

std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string current;
    bool in_quotes = false;

    for (size_t i = 0; i < line.size(); ++i) {
        const char ch = line[i];
        if (ch == '"') {
            in_quotes = !in_quotes;
            continue;
        }
        if (ch == ',' && !in_quotes) {
            fields.push_back(current);
            current.clear();
            continue;
        }
        current.push_back(ch);
    }

    fields.push_back(current);
    return fields;
}

std::string build_city_options_json(const std::string& csv_path) {
    std::ifstream file(csv_path.c_str());
    if (!file.is_open()) {
        return "{\"items\":[]}";
    }

    std::string line;
    std::getline(file, line);

    std::ostringstream oss;
    oss << "{\"items\":[";
    bool first = true;

    while (std::getline(file, line)) {
        std::vector<std::string> fields = split_csv_line(line);
        if (fields.size() < 6) {
            continue;
        }

        const std::string& district_id = trim(fields[0]);
        const std::string& province = trim(fields[1]);
        const std::string& city = trim(fields[2]);
        const std::string& city_geocode = trim(fields[3]);
        const std::string& district = trim(fields[4]);

        if (district_id.empty() || district_id != city_geocode) {
            continue;
        }

        const std::string city_name = city.empty() ? district : city;
        const std::string display_name = province == city_name ? city_name : province + " " + city_name;

        if (!first) {
            oss << ",";
        }
        first = false;
        oss << "{"
            << "\"district_id\":\"" << json_escape(district_id) << "\","
            << "\"city_name\":\"" << json_escape(city_name) << "\","
            << "\"display_name\":\"" << json_escape(display_name) << "\""
            << "}";
    }

    oss << "]}";
    return oss.str();
}

std::vector<std::string> list_jsonl_files(const std::string& logs_dir) {
    std::vector<std::string> files;
    const std::string pattern = normalize_separators(join_path(logs_dir, "*.jsonl"));

    WIN32_FIND_DATAA find_data;
    HANDLE handle = FindFirstFileA(pattern.c_str(), &find_data);
    if (handle == INVALID_HANDLE_VALUE) {
        return files;
    }

    do {
        if ((find_data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) == 0) {
            files.push_back(find_data.cFileName);
        }
    } while (FindNextFileA(handle, &find_data));

    FindClose(handle);
    std::sort(files.begin(), files.end());
    return files;
}

std::string build_history_item_json(const std::string& raw_line, const std::string& file_name, size_t line_index) {
    const std::string line = trim(raw_line);
    if (line.size() >= 2 && line[line.size() - 1] == '}') {
        std::ostringstream oss;
        oss << line.substr(0, line.size() - 1)
            << ",\"_log_file\":\"" << json_escape(file_name) << "\""
            << ",\"_line_index\":" << line_index
            << "}";
        return oss.str();
    }

    std::ostringstream fallback;
    fallback << "{"
             << "\"raw_line\":\"" << json_escape(line) << "\","
             << "\"_log_file\":\"" << json_escape(file_name) << "\","
             << "\"_line_index\":" << line_index
             << "}";
    return fallback.str();
}

std::string build_history_json(const std::string& logs_dir, size_t limit) {
    if (!is_directory_path(logs_dir)) {
        return "{\"items\":[]}";
    }

    std::vector<std::string> files = list_jsonl_files(logs_dir);
    std::ostringstream oss;
    oss << "{\"items\":[";
    bool first = true;
    size_t count = 0;

    for (std::vector<std::string>::reverse_iterator file_it = files.rbegin(); file_it != files.rend() && count < limit; ++file_it) {
        const std::string file_path = join_path(logs_dir, *file_it);
        std::ifstream file(file_path.c_str());
        if (!file.is_open()) {
            continue;
        }

        std::vector<std::string> lines;
        std::string line;
        while (std::getline(file, line)) {
            line = trim(line);
            if (!line.empty()) {
                lines.push_back(line);
            }
        }

        for (size_t reverse_index = 0; reverse_index < lines.size() && count < limit; ++reverse_index) {
            const size_t line_index = lines.size() - 1 - reverse_index;
            if (!first) {
                oss << ",";
            }
            first = false;
            oss << build_history_item_json(lines[line_index], *file_it, line_index);
            ++count;
        }
    }

    oss << "]}";
    return oss.str();
}

bool delete_history_records(
    const std::string& logs_dir,
    const std::string& conversation_id,
    const std::string& log_file,
    int line_index,
    std::string& error_message
) {
    error_message.clear();
    if (!is_directory_path(logs_dir)) {
        error_message = "History logs directory not found";
        return false;
    }

    const bool delete_by_conversation = !conversation_id.empty();
    const bool delete_by_position = !log_file.empty() && line_index >= 0;
    if (!delete_by_conversation && !delete_by_position) {
        error_message = "Missing conversation_id or log_file/line_index";
        return false;
    }

    // 验证 log_file 不包含路径遍历字符，且扩展名必须为 .jsonl
    if (!log_file.empty()) {
        if (log_file.find("..") != std::string::npos ||
            log_file.find("/") != std::string::npos ||
            log_file.find("\\") != std::string::npos) {
            error_message = "Invalid log_file parameter";
            return false;
        }
        if (log_file.size() < 6 || log_file.substr(log_file.size() - 6) != ".jsonl") {
            error_message = "Log file must be a .jsonl file";
            return false;
        }
    }

    std::vector<std::string> files = list_jsonl_files(logs_dir);
    bool removed = false;

    for (size_t file_idx = 0; file_idx < files.size(); ++file_idx) {
        const std::string& current_file = files[file_idx];
        if (delete_by_position && current_file != log_file) {
            continue;
        }

        const std::string file_path = join_path(logs_dir, current_file);
        std::ifstream input(file_path.c_str());
        if (!input.is_open()) {
            continue;
        }

        std::vector<std::string> kept_lines;
        std::string line;
        int current_line_index = 0;

        while (std::getline(input, line)) {
            const std::string trimmed_line = trim(line);
            if (trimmed_line.empty()) {
                continue;
            }

            bool should_delete = false;
            if (delete_by_conversation) {
                std::string parsed_conversation_id;
                should_delete =
                    extract_json_string(trimmed_line, "conversation_id", parsed_conversation_id) &&
                    parsed_conversation_id == conversation_id;
            } else if (current_line_index == line_index) {
                should_delete = true;
            }

            if (should_delete) {
                removed = true;
            } else {
                kept_lines.push_back(trimmed_line);
            }

            ++current_line_index;
        }
        input.close();

        if ((delete_by_conversation && removed) || (delete_by_position && current_file == log_file)) {
            std::ostringstream output;
            for (size_t i = 0; i < kept_lines.size(); ++i) {
                if (i > 0) {
                    output << "\n";
                }
                output << kept_lines[i];
            }

            if (!write_file(file_path, output.str())) {
                error_message = "Failed to rewrite history file";
                return false;
            }

            if (delete_by_position) {
                break;
            }
        }
    }

    if (!removed) {
        error_message = "History item not found";
        return false;
    }

    return true;
}

bool extract_json_string(const std::string& body, const std::string& key, std::string& value) {
    const std::string token = "\"" + key + "\"";
    size_t key_pos = body.find(token);
    if (key_pos == std::string::npos) {
        return false;
    }

    size_t colon_pos = body.find(':', key_pos + token.size());
    if (colon_pos == std::string::npos) {
        return false;
    }

    size_t pos = colon_pos + 1;
    while (pos < body.size() && std::isspace(static_cast<unsigned char>(body[pos]))) {
        ++pos;
    }

    if (pos >= body.size() || body[pos] != '"') {
        return false;
    }

    ++pos;
    value.clear();
    while (pos < body.size()) {
        char ch = body[pos++];
        if (ch == '\\' && pos < body.size()) {
            char escaped = body[pos++];
            switch (escaped) {
                case '"':
                case '\\':
                case '/':
                    value.push_back(escaped);
                    break;
                case 'b':
                    value.push_back('\b');
                    break;
                case 'f':
                    value.push_back('\f');
                    break;
                case 'n':
                    value.push_back('\n');
                    break;
                case 'r':
                    value.push_back('\r');
                    break;
                case 't':
                    value.push_back('\t');
                    break;
                default:
                    value.push_back(escaped);
                    break;
            }
        } else if (ch == '"') {
            return true;
        } else {
            value.push_back(ch);
        }
    }

    return false;
}

bool extract_json_bool(const std::string& body, const std::string& key, bool& value) {
    const std::string token = "\"" + key + "\"";
    size_t key_pos = body.find(token);
    if (key_pos == std::string::npos) {
        return false;
    }

    size_t colon_pos = body.find(':', key_pos + token.size());
    if (colon_pos == std::string::npos) {
        return false;
    }

    size_t pos = colon_pos + 1;
    while (pos < body.size() && std::isspace(static_cast<unsigned char>(body[pos]))) {
        ++pos;
    }

    if (body.compare(pos, 4, "true") == 0) {
        value = true;
        return true;
    }

    if (body.compare(pos, 5, "false") == 0) {
        value = false;
        return true;
    }

    return false;
}

bool extract_json_int(const std::string& body, const std::string& key, int& value) {
    const std::string token = "\"" + key + "\"";
    size_t key_pos = body.find(token);
    if (key_pos == std::string::npos) {
        return false;
    }

    size_t colon_pos = body.find(':', key_pos + token.size());
    if (colon_pos == std::string::npos) {
        return false;
    }

    size_t pos = colon_pos + 1;
    while (pos < body.size() && std::isspace(static_cast<unsigned char>(body[pos]))) {
        ++pos;
    }

    size_t end = pos;
    if (end < body.size() && (body[end] == '-' || body[end] == '+')) {
        ++end;
    }
    while (end < body.size() && std::isdigit(static_cast<unsigned char>(body[end]))) {
        ++end;
    }
    if (end == pos || (end == pos + 1 && (body[pos] == '-' || body[pos] == '+'))) {
        return false;
    }

    value = std::atoi(body.substr(pos, end - pos).c_str());
    return true;
}

bool parse_chat_request(const std::string& body, ChatRequest& request) {
    if (!extract_json_string(body, "user_input", request.user_input)) {
        return false;
    }

    extract_json_string(body, "personal_info", request.personal_info);
    extract_json_string(body, "weather", request.weather);
    extract_json_string(body, "primary_model_id", request.primary_model_id);
    extract_json_string(body, "secondary_model_id", request.secondary_model_id);
    extract_json_string(body, "primary_api_key", request.primary_api_key);
    extract_json_string(body, "secondary_api_key", request.secondary_api_key);
    extract_json_string(body, "conversation_id", request.conversation_id);
    extract_json_string(body, "conversation_title", request.conversation_title);
    extract_json_string(body, "conversation_context", request.conversation_context);
    extract_json_string(body, "recipe_profile", request.recipe_profile);
    extract_json_bool(body, "use_secondary", request.use_secondary);

    return !request.primary_model_id.empty();
}

std::string json_escape(const std::string& input) {
    std::string escaped;
    for (size_t i = 0; i < input.size(); ++i) {
        switch (input[i]) {
            case '\\':
                escaped += "\\\\";
                break;
            case '"':
                escaped += "\\\"";
                break;
            case '\n':
                escaped += "\\n";
                break;
            case '\r':
                escaped += "\\r";
                break;
            case '\t':
                escaped += "\\t";
                break;
            default:
                escaped.push_back(input[i]);
                break;
        }
    }
    return escaped;
}

std::string build_json_error(const std::string& message) {
    return std::string("{\"error\":\"") + json_escape(message) + "\"}";
}

std::string build_http_response(
    const std::string& content,
    const std::string& content_type,
    const std::string& status = "200 OK"
) {
    std::ostringstream oss;
    oss << "HTTP/1.1 " << status << "\r\n";
    oss << "Content-Type: " << content_type << "\r\n";
    oss << "Access-Control-Allow-Origin: http://localhost:8080\r\n";
    oss << "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n";
    oss << "Access-Control-Allow-Headers: Content-Type\r\n";
    oss << "Content-Length: " << content.size() << "\r\n";
    oss << "Connection: close\r\n\r\n";
    oss << content;
    return oss.str();
}

std::wstring utf8_to_wide(const std::string& input) {
    if (input.empty()) {
        return L"";
    }

    const int size = MultiByteToWideChar(CP_UTF8, 0, input.c_str(), -1, NULL, 0);
    if (size <= 0) {
        return L"";
    }

    std::wstring output(static_cast<size_t>(size - 1), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, input.c_str(), -1, &output[0], size);
    return output;
}

bool http_get_text(const std::wstring& url, std::string& response_body, std::string& error_message) {
    response_body.clear();
    error_message.clear();

    URL_COMPONENTS components;
    ZeroMemory(&components, sizeof(components));
    components.dwStructSize = sizeof(components);
    components.dwSchemeLength = static_cast<DWORD>(-1);
    components.dwHostNameLength = static_cast<DWORD>(-1);
    components.dwUrlPathLength = static_cast<DWORD>(-1);
    components.dwExtraInfoLength = static_cast<DWORD>(-1);

    if (!WinHttpCrackUrl(url.c_str(), 0, 0, &components)) {
        error_message = "Failed to parse weather request URL";
        return false;
    }

    const std::wstring host(components.lpszHostName, components.dwHostNameLength);
    std::wstring path(components.lpszUrlPath, components.dwUrlPathLength);
    if (components.dwExtraInfoLength > 0) {
        path.append(components.lpszExtraInfo, components.dwExtraInfoLength);
    }

    HINTERNET session = WinHttpOpen(L"AI-Diet-Assistant/1.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!session) {
        error_message = "Failed to initialize weather session";
        return false;
    }

    HINTERNET connect = WinHttpConnect(session, host.c_str(), components.nPort, 0);
    if (!connect) {
        WinHttpCloseHandle(session);
        error_message = "Failed to connect weather service";
        return false;
    }

    const DWORD flags = components.nScheme == INTERNET_SCHEME_HTTPS ? WINHTTP_FLAG_SECURE : 0;
    HINTERNET request = WinHttpOpenRequest(connect, L"GET", path.c_str(), NULL, WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, flags);
    if (!request) {
        WinHttpCloseHandle(connect);
        WinHttpCloseHandle(session);
        error_message = "Failed to create weather request";
        return false;
    }

    bool ok = WinHttpSendRequest(request, WINHTTP_NO_ADDITIONAL_HEADERS, 0, WINHTTP_NO_REQUEST_DATA, 0, 0, 0)
        && WinHttpReceiveResponse(request, NULL);

    if (!ok) {
        error_message = "Weather service request failed";
        WinHttpCloseHandle(request);
        WinHttpCloseHandle(connect);
        WinHttpCloseHandle(session);
        return false;
    }

    DWORD status_code = 0;
    DWORD status_code_size = sizeof(status_code);
    if (WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX, &status_code, &status_code_size, WINHTTP_NO_HEADER_INDEX)) {
        if (status_code >= 400) {
            error_message = "Weather service returned HTTP " + std::to_string(status_code);
        }
    }

    do {
        DWORD available = 0;
        if (!WinHttpQueryDataAvailable(request, &available)) {
            if (error_message.empty()) {
                error_message = "Failed to read weather response";
            }
            ok = false;
            break;
        }

        if (available == 0) {
            break;
        }

        std::vector<char> buffer(available);
        DWORD downloaded = 0;
        if (!WinHttpReadData(request, &buffer[0], available, &downloaded)) {
            if (error_message.empty()) {
                error_message = "Failed to read weather response";
            }
            ok = false;
            break;
        }

        response_body.append(buffer.data(), downloaded);
    } while (true);

    WinHttpCloseHandle(request);
    WinHttpCloseHandle(connect);
    WinHttpCloseHandle(session);
    return ok;
}

std::string fetch_weather_proxy_json(const std::string& district_id, const std::string& ak) {
    if (district_id.empty() || ak.empty()) {
        return build_json_error("Missing district_id or ak");
    }

    const std::string url =
        "https://api.map.baidu.com/weather/v1/?district_id=" + district_id +
        "&data_type=all&ak=" + ak;

    std::string response_body;
    std::string error_message;
    if (!http_get_text(utf8_to_wide(url), response_body, error_message)) {
        return build_json_error(error_message.empty() ? "Weather request failed" : error_message);
    }

    return response_body.empty() ? build_json_error("Weather service returned empty response") : response_body;
}

std::string get_mime_type(const std::string& path) {
    if (path.size() >= 3 && path.substr(path.size() - 3) == ".js") {
        return "application/javascript; charset=utf-8";
    }
    if (path.size() >= 4 && path.substr(path.size() - 4) == ".css") {
        return "text/css; charset=utf-8";
    }
    if (path.size() >= 5 && path.substr(path.size() - 5) == ".webp") {
        return "image/webp";
    }
    return "text/html; charset=utf-8";
}

bool read_file(const std::string& path, std::string& content) {
    std::ifstream file(path.c_str(), std::ios::binary);
    if (!file.is_open()) {
        return false;
    }

    std::ostringstream buffer;
    buffer << file.rdbuf();
    content = buffer.str();
    return true;
}

bool write_file(const std::string& path, const std::string& content) {
    std::ofstream file(path.c_str(), std::ios::binary | std::ios::trunc);
    if (!file.is_open()) {
        return false;
    }

    file << content;
    return file.good();
}

std::string map_static_file(const std::string& static_dir, const std::string& path) {
    if (path == "/" || path == "/index.html") {
        return static_dir + "/index.html";
    }
    if (path == "/script.js") {
        return static_dir + "/script.js";
    }
    if (path == "/style.css") {
        return static_dir + "/style.css";
    }
    if (path.rfind("/image/", 0) == 0 && path.find("..") == std::string::npos) {
        const std::string project_root = dirname(dirname(static_dir));
        return join_path(project_root, path.substr(1));
    }
    return "";
}

std::string quote_windows_arg(const std::string& arg) {
    std::string quoted = "\"";
    int backslash_count = 0;

    for (size_t i = 0; i < arg.size(); ++i) {
        char ch = arg[i];
        if (ch == '\\') {
            ++backslash_count;
            quoted.push_back(ch);
            continue;
        }

        if (ch == '"') {
            quoted.insert(quoted.end() - backslash_count, backslash_count, '\\');
            quoted.push_back('\\');
            quoted.push_back('"');
            backslash_count = 0;
            continue;
        }

        backslash_count = 0;
        quoted.push_back(ch);
    }

    if (backslash_count > 0) {
        quoted.append(backslash_count, '\\');
    }

    quoted.push_back('"');
    return quoted;
}

std::string build_chat_request_json(const ChatRequest& request) {
    std::ostringstream oss;
    oss << "{";
    oss << "\"user_input\":\"" << json_escape(request.user_input) << "\",";
    oss << "\"personal_info\":\"" << json_escape(request.personal_info) << "\",";
    oss << "\"weather\":\"" << json_escape(request.weather) << "\",";
    oss << "\"primary_model_id\":\"" << json_escape(request.primary_model_id) << "\",";
    oss << "\"secondary_model_id\":\"" << json_escape(request.secondary_model_id) << "\",";
    oss << "\"conversation_id\":\"" << json_escape(request.conversation_id) << "\",";
    oss << "\"conversation_title\":\"" << json_escape(request.conversation_title) << "\",";
    oss << "\"conversation_context\":\"" << json_escape(request.conversation_context) << "\",";
    oss << "\"recipe_profile\":" << (request.recipe_profile.empty() ? "[]" : request.recipe_profile) << ",";
    oss << "\"use_secondary\":" << (request.use_secondary ? "true" : "false");
    oss << "}";
    return oss.str();
}

bool write_temp_json_file(const std::string& content, std::string& temp_path) {
    char temp_dir[MAX_PATH];
    const DWORD dir_len = GetTempPathA(MAX_PATH, temp_dir);
    if (dir_len == 0 || dir_len > MAX_PATH) {
        return false;
    }

    char temp_file[MAX_PATH];
    if (GetTempFileNameA(temp_dir, "aid", 0, temp_file) == 0) {
        return false;
    }

    temp_path = temp_file;
    return write_file(temp_path, content);
}

bool run_process_capture(
    const std::string& command_line,
    const std::string& working_directory,
    std::string& output,
    DWORD& exit_code
) {
    SECURITY_ATTRIBUTES sa;
    sa.nLength = sizeof(sa);
    sa.lpSecurityDescriptor = NULL;
    sa.bInheritHandle = TRUE;

    HANDLE read_pipe = NULL;
    HANDLE write_pipe = NULL;
    if (!CreatePipe(&read_pipe, &write_pipe, &sa, 0)) {
        return false;
    }

    SetHandleInformation(read_pipe, HANDLE_FLAG_INHERIT, 0);

    STARTUPINFOA si;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = write_pipe;
    si.hStdError = write_pipe;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);

    PROCESS_INFORMATION pi;
    ZeroMemory(&pi, sizeof(pi));

    std::vector<char> mutable_command(command_line.begin(), command_line.end());
    mutable_command.push_back('\0');

    BOOL created = CreateProcessA(
        NULL,
        mutable_command.data(),
        NULL,
        NULL,
        TRUE,
        CREATE_NO_WINDOW,
        NULL,
        working_directory.empty() ? NULL : working_directory.c_str(),
        &si,
        &pi
    );

    CloseHandle(write_pipe);

    if (!created) {
        CloseHandle(read_pipe);
        return false;
    }

    char buffer[4096];
    DWORD bytes_read = 0;
    output.clear();
    while (ReadFile(read_pipe, buffer, sizeof(buffer), &bytes_read, NULL) && bytes_read > 0) {
        output.append(buffer, bytes_read);
    }

    WaitForSingleObject(pi.hProcess, INFINITE);
    GetExitCodeProcess(pi.hProcess, &exit_code);

    CloseHandle(read_pipe);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return true;
}

std::string call_python_ai(const ChatRequest& request, const std::string& python_script) {
    std::string request_file_path;
    if (!write_temp_json_file(build_chat_request_json(request), request_file_path)) {
        return build_json_error("Failed to create temporary request file");
    }

    // 通过环境变量传递 API Key，避免出现在命令行参数中
    const char* env_primary = "AI_DIET_PRIMARY_API_KEY";
    const char* env_secondary = "AI_DIET_SECONDARY_API_KEY";
    char old_primary[256] = {0};
    char old_secondary[256] = {0};
    GetEnvironmentVariableA(env_primary, old_primary, sizeof(old_primary));
    GetEnvironmentVariableA(env_secondary, old_secondary, sizeof(old_secondary));
    SetEnvironmentVariableA(env_primary, request.primary_api_key.c_str());
    SetEnvironmentVariableA(env_secondary, request.secondary_api_key.c_str());

    std::ostringstream command;
    command << "python " << quote_windows_arg(python_script)
            << " --request_file " << quote_windows_arg(request_file_path);

    std::cout << "[INFO] Executing: " << command.str() << std::endl;

    std::string output;
    DWORD exit_code = 0;
    const bool executed = run_process_capture(command.str(), dirname(python_script), output, exit_code);
    DeleteFileA(request_file_path.c_str());

    // 恢复原环境变量值
    SetEnvironmentVariableA(env_primary, old_primary);
    SetEnvironmentVariableA(env_secondary, old_secondary);

    if (!executed) {
        return build_json_error("Failed to execute Python script");
    }

    std::cout << "[INFO] Python output: " << output << std::endl;

    size_t brace_start = output.find('{');
    size_t brace_end = output.rfind('}');
    if (brace_start != std::string::npos && brace_end != std::string::npos && brace_end > brace_start) {
        return output.substr(brace_start, brace_end - brace_start + 1);
    }

    if (exit_code != 0) {
        return build_json_error("Python script exited with code " + std::to_string(exit_code) + ": " + output);
    }

    return build_json_error("Python script returned invalid JSON");
}

void send_response(SOCKET client_socket, const std::string& response) {
    send(client_socket, response.c_str(), static_cast<int>(response.size()), 0);
}

// 简单的滑动窗口速率限制（内存存储，进程重启后清零）
std::map<std::string, std::vector<time_t>> rate_limit_records;

bool check_rate_limit(const std::string& endpoint, int max_requests, int window_seconds) {
    time_t now = time(nullptr);
    std::vector<time_t>& timestamps = rate_limit_records[endpoint];
    // 清理过期记录
    timestamps.erase(
        std::remove_if(timestamps.begin(), timestamps.end(),
            [now, window_seconds](time_t t) { return now - t > window_seconds; }),
        timestamps.end()
    );
    if (static_cast<int>(timestamps.size()) >= max_requests) {
        return false;
    }
    timestamps.push_back(now);
    return true;
}

void handle_request(
    SOCKET client_socket,
    const std::string& raw_request,
    const std::string& static_dir,
    const std::string& python_script,
    const std::string& config_path,
    const std::string& logs_dir,
    const std::string& weather_city_csv
) {
    std::istringstream header_stream(raw_request);
    std::string request_line;
    std::getline(header_stream, request_line);
    if (!request_line.empty() && request_line[request_line.size() - 1] == '\r') {
        request_line.erase(request_line.size() - 1);
    }

    const std::string method = get_request_line_part(request_line, 0);
    const std::string path = get_request_line_part(request_line, 1);
    const std::string route = get_request_path_only(path);

    if (method == "OPTIONS") {
        send_response(client_socket, build_http_response("", "text/plain; charset=utf-8"));
        return;
    }

    // 对 POST 写操作检查 Origin/Referer 头，仅放行 localhost 来源
    if (method == "POST") {
        bool has_local_origin = false;
        const char* origin_patterns[] = {
            "Origin: http://localhost", "Origin: http://127.0.0.1",
            "Referer: http://localhost", "Referer: http://127.0.0.1"
        };
        for (size_t i = 0; i < sizeof(origin_patterns) / sizeof(origin_patterns[0]); ++i) {
            if (raw_request.find(origin_patterns[i]) != std::string::npos) {
                has_local_origin = true;
                break;
            }
        }
        // 如果没有 Origin/Referer 头（如 curl 直接调用），也放行（本地 CLI 工具场景）
        bool has_origin_header = raw_request.find("Origin:") != std::string::npos;
        bool has_referer_header = raw_request.find("Referer:") != std::string::npos;
        if ((has_origin_header || has_referer_header) && !has_local_origin) {
            send_response(
                client_socket,
                build_http_response(
                    build_json_error("跨域请求不被允许"),
                    "application/json; charset=utf-8",
                    "403 Forbidden"
                )
            );
            return;
        }
    }

    if (method == "GET") {
        if (route == "/api/config") {
            std::string content;
            if (read_file(config_path, content)) {
                // 脱敏 api_key 和 ak 字段，避免密钥泄露
                size_t pos = 0;
                while ((pos = content.find("\"api_key\": \"", pos)) != std::string::npos) {
                    pos += 12;  // 跳过 "\"api_key\": \""
                    size_t end_pos = content.find("\"", pos);
                    if (end_pos != std::string::npos && end_pos > pos) {
                        content.replace(pos, end_pos - pos, "***");
                    }
                }
                pos = 0;
                while ((pos = content.find("\"ak\": \"", pos)) != std::string::npos) {
                    pos += 7;  // 跳过 "\"ak\": \""
                    size_t end_pos = content.find("\"", pos);
                    if (end_pos != std::string::npos && end_pos > pos) {
                        content.replace(pos, end_pos - pos, "***");
                    }
                }
                send_response(client_socket, build_http_response(content, "application/json; charset=utf-8"));
            } else {
                send_response(
                    client_socket,
                    build_http_response(build_json_error("Failed to read config file"), "application/json; charset=utf-8", "500 Internal Server Error")
                );
            }
            return;
        }

        if (route == "/api/weather/cities") {
            send_response(
                client_socket,
                build_http_response(build_city_options_json(weather_city_csv), "application/json; charset=utf-8")
            );
            return;
        }

        if (route == "/api/weather") {
            const std::string district_id = get_query_param(path, "district_id");
            const std::string ak = get_query_param(path, "ak");
            const std::string weather_json = fetch_weather_proxy_json(district_id, ak);
            send_response(
                client_socket,
                build_http_response(weather_json, "application/json; charset=utf-8")
            );
            return;
        }

        if (route == "/api/history") {
            const std::string limit_text = get_query_param(path, "limit");
            size_t limit = 20;
            if (!limit_text.empty()) {
                const int parsed_limit = std::atoi(limit_text.c_str());
                if (parsed_limit > 0) {
                    limit = static_cast<size_t>(parsed_limit);
                }
            }

            send_response(
                client_socket,
                build_http_response(build_history_json(logs_dir, limit), "application/json; charset=utf-8")
            );
            return;
        }

        std::string file_path = map_static_file(static_dir, route);
        std::string content;
        if (!file_path.empty() && read_file(file_path, content)) {
            send_response(client_socket, build_http_response(content, get_mime_type(file_path)));
            return;
        }

        send_response(
            client_socket,
            build_http_response("<h1>404 Not Found</h1>", "text/html; charset=utf-8", "404 Not Found")
        );
        return;
    }

    if (method == "POST" && route == "/api/chat") {
        // 速率限制：每分钟最多 6 次请求
        if (!check_rate_limit("/api/chat", 6, 60)) {
            send_response(
                client_socket,
                build_http_response(
                    build_json_error("请求过于频繁，请稍后再试"),
                    "application/json; charset=utf-8",
                    "429 Too Many Requests"
                )
            );
            return;
        }

        const std::string body = get_request_body(raw_request);
        ChatRequest chat_request;
        if (!parse_chat_request(body, chat_request)) {
            send_response(
                client_socket,
                build_http_response(build_json_error("Invalid request JSON"), "application/json; charset=utf-8", "400 Bad Request")
            );
            return;
        }

        // 限制用户输入长度，防止滥用
        if (chat_request.user_input.size() > 2000) {
            chat_request.user_input = chat_request.user_input.substr(0, 2000);
        }

        const std::string content = call_python_ai(chat_request, python_script);
        send_response(client_socket, build_http_response(content, "application/json; charset=utf-8"));
        return;
    }

    if (method == "POST" && route == "/api/history/delete") {
        const std::string body = get_request_body(raw_request);
        std::string conversation_id;
        std::string log_file;
        int line_index = -1;

        extract_json_string(body, "conversation_id", conversation_id);
        extract_json_string(body, "log_file", log_file);
        extract_json_int(body, "line_index", line_index);

        std::string error_message;
        if (!delete_history_records(logs_dir, conversation_id, log_file, line_index, error_message)) {
            send_response(
                client_socket,
                build_http_response(build_json_error(error_message), "application/json; charset=utf-8", "400 Bad Request")
            );
            return;
        }

        send_response(
            client_socket,
            build_http_response("{\"ok\":true}", "application/json; charset=utf-8")
        );
        return;
    }

    if (method == "POST" && route == "/api/config") {
        const std::string body = trim(get_request_body(raw_request));
        if (body.size() < 2 || body[0] != '{' || body[body.size() - 1] != '}') {
            send_response(
                client_socket,
                build_http_response(build_json_error("Invalid config JSON"), "application/json; charset=utf-8", "400 Bad Request")
            );
            return;
        }

        // 禁止通过 API 修改服务器核心运行参数
        const char* forbidden_fields[] = {"python_script", "static_dir", "port", "logs_dir"};
        for (size_t i = 0; i < sizeof(forbidden_fields) / sizeof(forbidden_fields[0]); ++i) {
            std::string token = "\"" + std::string(forbidden_fields[i]) + "\"";
            if (body.find(token) != std::string::npos) {
                send_response(
                    client_socket,
                    build_http_response(
                        build_json_error("禁止通过 API 修改字段: " + std::string(forbidden_fields[i])),
                        "application/json; charset=utf-8", "400 Bad Request"
                    )
                );
                return;
            }
        }

        if (!write_file(config_path, body)) {
            send_response(
                client_socket,
                build_http_response(build_json_error("Failed to write config file"), "application/json; charset=utf-8", "500 Internal Server Error")
            );
            return;
        }

        send_response(
            client_socket,
            build_http_response("{\"ok\":true}", "application/json; charset=utf-8")
        );
        return;
    }

    send_response(
        client_socket,
        build_http_response(build_json_error("Unsupported route"), "application/json; charset=utf-8", "404 Not Found")
    );
}

}  // namespace

int main() {
    const RuntimeConfig config = load_runtime_config();
    const int port = config.port > 0 ? config.port : 8080;
    const std::string static_dir = config.static_dir;
    const std::string python_script = config.python_script;
    const std::string config_path = config.config_path;
    const std::string logs_dir = config.logs_dir;
    const std::string weather_city_csv = config.weather_city_csv;

    if (!is_directory_path(static_dir)) {
        std::cerr << "[FATAL] Static directory not found: " << static_dir << std::endl;
        return 1;
    }
    if (!path_exists(python_script)) {
        std::cerr << "[FATAL] Python script not found: " << python_script << std::endl;
        return 1;
    }

    if (!init_winsock()) {
        std::cerr << "[FATAL] Failed to initialize WinSock." << std::endl;
        return 1;
    }

    SOCKET server_socket = create_server_socket(port);
    if (server_socket == INVALID_SOCKET) {
        std::cerr << "[FATAL] Failed to create server socket." << std::endl;
        cleanup_winsock();
        return 1;
    }

    std::cout << "[INFO] Server starting on port " << port << std::endl;
    std::cout << "[INFO] Static dir: " << static_dir << std::endl;
    std::cout << "[INFO] Python script: " << python_script << std::endl;
    std::cout << "[INFO] Config path: " << config_path << std::endl;
    std::cout << "[INFO] Logs dir: " << logs_dir << std::endl;
    std::cout << "[INFO] Weather city csv: " << weather_city_csv << std::endl;

    while (true) {
        SOCKET client_socket = accept(server_socket, NULL, NULL);
        if (client_socket == INVALID_SOCKET) {
            continue;
        }

        std::string raw_request;
        if (receive_http_request(client_socket, raw_request)) {
            handle_request(client_socket, raw_request, static_dir, python_script, config_path, logs_dir, weather_city_csv);
        }

        closesocket(client_socket);
    }

    closesocket(server_socket);
    cleanup_winsock();
    return 0;
}
