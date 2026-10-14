#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

/* Use paths relative to this EXE, including folders with spaces/Korean names. */
int wmain(void) {
    static wchar_t root[32768], python[32768], command[32768];
    DWORD size = GetModuleFileNameW(NULL, root, 32768);
    if (!size || size >= 32768) return 1;
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return 1;
    *slash = L'\0';
    if (wcslen(root) > 15000) return 1;
    wcscpy(python, root);
    wcscat(python, L"\\runtime\\python.exe");
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"압축을 모두 풀고 프로그램 폴더 전체를 보관해 주세요. runtime 폴더가 필요합니다.",
                    L"사내결재시스템", MB_OK | MB_ICONERROR);
        return 1;
    }
    wcscpy(command, L"\"");
    wcscat(command, python);
    wcscat(command, L"\" -X utf8 -u \"");
    wcscat(command, root);
    wcscat(command, L"\\portable.py\"");
    wchar_t *tail = GetCommandLineW();
    if (*tail == L'"') {
        tail++;
        while (*tail && *tail != L'"') tail++;
        if (*tail) tail++;
    } else {
        while (*tail && *tail != L' ' && *tail != L'\t') tail++;
    }
    if (wcslen(command) + wcslen(tail) >= 32768) return 1;
    wcscat(command, tail);
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    SetConsoleOutputCP(CP_UTF8);
    if (!CreateProcessW(python, command, NULL, NULL, TRUE, 0, NULL, root, &startup, &process)) {
        MessageBoxW(NULL, L"프로그램을 실행하지 못했습니다. 일반 폴더에 압축을 모두 푼 뒤 다시 실행해 주세요.",
                    L"사내결재시스템", MB_OK | MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    WaitForSingleObject(process.hProcess, INFINITE);
    DWORD result = 1;
    GetExitCodeProcess(process.hProcess, &result);
    CloseHandle(process.hProcess);
    return (int)result;
}
