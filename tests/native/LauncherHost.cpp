#include <Windows.h>
#include <RED4ext/Api/v1/EMainReason.hpp>
#include <RED4ext/Api/v1/Sdk.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

int wmain(int argc, wchar_t** argv) {
    if (argc < 2 || argc > 3) return 2;
    const bool realWorker = argc == 3 && std::wstring(argv[2]) == L"--real-worker";
    const std::filesystem::path dll(argv[1]);
    auto module = LoadLibraryW(dll.c_str());
    if (!module) return 3;
    using Entry = bool(__cdecl*)(HMODULE, RED4ext::v1::EMainReason, const RED4ext::v1::Sdk*);
    const auto entry = reinterpret_cast<Entry>(GetProcAddress(module, "Main"));
    if (!entry || !entry(module, RED4ext::v1::EMainReason::Load, nullptr)) return 4;
    const auto report = dll.parent_path() / (realWorker ? L"data/runtime.pid" : L"launcher-test.txt");
    for (int count = 0; count < 400 && !std::filesystem::exists(report); ++count) Sleep(50);
    std::ifstream file(report);
    std::string line;
    std::getline(file, line);
    if (!realWorker && !line.starts_with("pid=")) return 5;
    if (line.empty()) return 5;
    const auto pid = std::stoul(realWorker ? line : line.substr(4));
    auto child = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!child || WaitForSingleObject(child, 0) != WAIT_TIMEOUT) return 6;
    // Loading twice must keep the same child, not launch duplicate converters.
    if (!entry(module, RED4ext::v1::EMainReason::Load, nullptr)) return 7;
    if (!entry(module, RED4ext::v1::EMainReason::Unload, nullptr)) return 8;
    const bool exited = WaitForSingleObject(child, 5000) == WAIT_OBJECT_0;
    CloseHandle(child);
    FreeLibrary(module);
    if (!exited) return 9;
    std::cout << "Launcher started and stopped its bundled child successfully\n";
    return 0;
}
