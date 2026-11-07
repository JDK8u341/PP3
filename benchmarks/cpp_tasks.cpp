// 同题的惯用 C++ 算法基线：不模拟 DSL 内存或 Python I/O，不能声称完整语义等价。
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <iterator>
#include <numeric>
#include <sstream>
#include <string>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

std::string solve(const std::string& name, const std::string& input) {
    if (name == "P003") return std::to_string(std::stoll(input)) + "\n";
    if (name == "P004" || name == "P005") {
        std::istringstream stream(input);
        long long a, b;
        stream >> a >> b;
        return std::to_string(name == "P004" ? a * b : std::gcd(a, b)) + "\n";
    }
    std::string output = input;
    if (name == "P006") {
        for (char& c : output) {
            if (c >= 'A' && c <= 'Z') c = 'A' + (c - 'A' + 13) % 26;
            else if (c >= 'a' && c <= 'z') c = 'a' + (c - 'a' + 13) % 26;
        }
    } else if (name == "P007") {
        std::sort(output.begin(), output.end(), [](unsigned char a, unsigned char b) { return a < b; });
    } else {
        size_t lines = 0, words = 0;
        bool inside = false;
        for (unsigned char c : input) {
            if (c == '\n') ++lines;
            bool blank = (c >= 9 && c <= 13) || c == 32;
            if (!blank && !inside) ++words;
            inside = !blank;
        }
        output = std::to_string(lines) + " " + std::to_string(words) + " " + std::to_string(input.size()) + "\n";
    }
    return output;
}

int main(int argc, char** argv) {
    if (argc != 3) return 2;
#ifdef _WIN32
    _setmode(_fileno(stdin), _O_BINARY);
#endif
    std::string name = argv[1];
    size_t repeat = std::stoull(argv[2]);
    std::string input(std::istreambuf_iterator<char>(std::cin), {});
    if (!repeat) {
#ifdef _WIN32
        _setmode(_fileno(stdout), _O_BINARY);
#endif
        std::cout << solve(name, input);
        return 0;
    }
    uint64_t checksum = 0;
    auto start = std::chrono::steady_clock::now();
    for (size_t i = 0; i < repeat; ++i) {
        auto output = solve(name, input);
        for (unsigned char c : output) checksum += c;
    }
    double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() / repeat;
    std::cout.precision(17);
    std::cout << seconds << " " << checksum << "\n";
}
