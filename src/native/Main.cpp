#include <Windows.h>
#include <RED4ext/Api/ApiVersion.hpp>
#include <RED4ext/Api/v1/EMainReason.hpp>
#include <RED4ext/Api/v1/PluginInfo.hpp>
#include <RED4ext/Api/v1/Sdk.hpp>
#include <RED4ext/Version.hpp>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
namespace fs = std::filesystem;
HANDLE job = nullptr;
HANDLE worker = nullptr;

fs::path modulePath(HMODULE module) {
    std::vector<wchar_t> buffer(32768);
    const DWORD size = GetModuleFileNameW(module, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (!size || size >= buffer.size()) throw std::runtime_error("Cannot locate game/plugin executable");
    return fs::path(std::wstring(buffer.data(), size));
}

std::wstring quote(const std::wstring& argument) {
    std::wstring result = L"\"";
    size_t slashes = 0;
    for (const auto character : argument) {
        if (character == L'\\') { ++slashes; continue; }
        result.append(slashes * (character == L'\"' ? 2 : 1), L'\\');
        slashes = 0;
        if (character == L'\"') result += L'\\';
        result += character;
    }
    result.append(slashes * 2, L'\\');
    result += L'\"';
    return result;
}

void stop() {
    // The job also contains converter subprocesses. It closes with the game;
    // no service, task scheduler entry or background agent survives it.
    if (job) { CloseHandle(job); job = nullptr; }
    if (worker) { CloseHandle(worker); worker = nullptr; }
}

void start(HMODULE plugin) {
    if (worker && WaitForSingleObject(worker, 0) == WAIT_TIMEOUT) return;
    stop();
    const auto pluginRoot = modulePath(plugin).parent_path();
    const auto gameExe = modulePath(nullptr);
    const auto game = gameExe.parent_path().parent_path().parent_path();
    if (!fs::equivalent(game / L"bin/x64/Cyberpunk2077.exe", gameExe))
        throw std::runtime_error("NPV Maker must run inside Cyberpunk2077.exe");
    const auto executable = pluginRoot / L"runtime/NPVMakerConverter.exe";
    if (!fs::is_regular_file(executable))
        throw std::runtime_error("NPV Maker converter is missing from the mod package");
    auto command = quote(executable.wstring()) + L" --game-root " + quote(game.wstring())
        + L" --plugin-root " + quote(pluginRoot.wstring())
        + L" --parent-pid " + std::to_wstring(GetCurrentProcessId());

    job = CreateJobObjectW(nullptr, nullptr);
    if (!job) throw std::runtime_error("Cannot create converter lifetime job");
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
        stop();
        throw std::runtime_error("Cannot configure converter lifetime");
    }
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, FALSE,
                        CREATE_SUSPENDED | CREATE_NO_WINDOW, nullptr, pluginRoot.c_str(), &startup, &process)) {
        stop();
        throw std::runtime_error("Cannot start bundled converter");
    }
    if (!AssignProcessToJobObject(job, process.hProcess)) {
        TerminateProcess(process.hProcess, 1);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        stop();
        throw std::runtime_error("Cannot bind converter lifetime to the game");
    }
    worker = process.hProcess;
    const DWORD resumed = ResumeThread(process.hThread);
    CloseHandle(process.hThread);
    if (resumed == static_cast<DWORD>(-1)) {
        stop();
        throw std::runtime_error("Cannot resume bundled converter");
    }
}
}

extern "C" __declspec(dllexport) bool __cdecl Main(RED4ext::v1::PluginHandle handle,
    RED4ext::v1::EMainReason reason, const RED4ext::v1::Sdk* sdk) {
    try {
        if (reason == RED4ext::v1::EMainReason::Load) start(handle);
        else if (reason == RED4ext::v1::EMainReason::Unload) stop();
        return true;
    } catch (const std::exception& error) {
        stop();
        if (sdk && sdk->logger && sdk->logger->Error) sdk->logger->Error(handle, error.what());
        return false;
    }
}

extern "C" __declspec(dllexport) void __cdecl Query(RED4ext::v1::PluginInfo* info) {
    info->name = L"NPV Maker Runtime";
    info->author = L"NPV Maker";
    info->version = {0, 4, 20, {0, 0}};
    info->sdk = {RED4EXT_VER_MAJOR, RED4EXT_VER_MINOR, RED4EXT_VER_PATCH, {0, 0}};
    // This component uses RED4ext only as a loader, without engine addresses.
    info->runtime = {0xffff, 0xffff, 0xffff, 0xffff};
}

extern "C" __declspec(dllexport) uint32_t __cdecl Supports() { return RED4EXT_API_VERSION_1; }
