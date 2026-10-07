#include <Windows.h>
#include <filesystem>
#include <fstream>

int wmain(int argc, wchar_t** argv) {
    std::ofstream result(std::filesystem::current_path() / L"launcher-test.txt");
    result << "pid=" << GetCurrentProcessId() << '\n';
    for (int index = 1; index < argc; ++index) {
        const auto bytes = std::filesystem::path(argv[index]).u8string();
        result.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
        result << '\n';
    }
    result.close();
    Sleep(INFINITE);
    return 0;
}
