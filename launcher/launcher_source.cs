using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Text.RegularExpressions;

internal static class LauncherProgram
{
    [STAThread]
    private static int Main()
    {
        try
        {
            var exeDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var rootDir = Path.GetDirectoryName(exeDir);
            var serverDir = Path.Combine(rootDir, "server");
            var aiCoreDir = Path.Combine(rootDir, "ai_core");
            var venvPython = Path.Combine(aiCoreDir, "ai_diet_env", "Scripts", "python.exe");
            var venvScripts = Path.Combine(aiCoreDir, "ai_diet_env", "Scripts");

            WriteStep("Check project files");
            EnsureFileExists(Path.Combine(serverDir, "run_server.py"),
                "run_server.py not found. Put the launcher exe in the project root.");

            WriteStep("Stop old backend");
            StopOldBackend("backend");
            StopOldBackend("run_server");

            WriteStep("Prepare Python");
            string requirementsTxt = Path.Combine(aiCoreDir, "requirements.txt");

            // 查找可用的 Python（依次搜索 conda 环境、venv、PATH）
            string foundPython = FindPythonExe(rootDir, aiCoreDir);
            if (string.IsNullOrEmpty(foundPython))
            {
                // 尝试 python3 作为后备
                foundPython = FindExecutableInPath("python3.exe");
            }
            if (string.IsNullOrEmpty(foundPython))
            {
                Console.Error.WriteLine("Python not found. Please install Python or activate conda environment.");
                Console.Error.WriteLine("Press any key to exit...");
                Console.ReadKey();
                return 1;
            }
            Console.WriteLine("Using Python: " + foundPython);

            // conda 环境通常已有依赖，跳过检查
            bool pythonReady = foundPython.Contains("anaconda") || foundPython.Contains("conda");
            if (!pythonReady)
            {
                pythonReady = RunProcessCheck(foundPython,
                    "-c \"import flask, chromadb, sentence_transformers\"", rootDir);
            }

            if (!pythonReady)
            {
                if (File.Exists(venvPython))
                {
                    PrependPath(venvScripts);
                    Console.WriteLine("Use venv Python: " + venvPython);
                    foundPython = venvPython;
                    if (File.Exists(requirementsTxt))
                    {
                        Console.WriteLine("Installing Python dependencies into venv...");
                        RunProcess(foundPython, "-m pip install -r \"" + requirementsTxt + "\"", rootDir);
                    }
                }
                else
                {
                    Console.WriteLine("Creating virtual environment...");
                    RunProcess(foundPython, "-m venv \"" + Path.Combine(aiCoreDir, "ai_diet_env") + "\"", rootDir);
                    if (File.Exists(venvPython))
                    {
                        PrependPath(venvScripts);
                        foundPython = venvPython;
                        Console.WriteLine("Venv created. Installing dependencies...");
                        if (File.Exists(requirementsTxt))
                        {
                            RunProcess(foundPython, "-m pip install -r \"" + requirementsTxt + "\"", rootDir);
                        }
                    }
                }
            }

            var configJsonPath = Path.Combine(serverDir, "Config.json");
            var configExamplePath = Path.Combine(serverDir, "Config.example.json");
            if (!File.Exists(configJsonPath) && File.Exists(configExamplePath))
            {
                File.Copy(configExamplePath, configJsonPath);
                Console.WriteLine("Created Config.json from template.");
            }
            var needOllama = RequiresOllama(configJsonPath);
            if (needOllama)
            {
                WriteStep("Check Ollama");
                EnsureOllamaRunning(rootDir);
            }

            WriteStep("Start Python backend");
            var backendProcess = new Process();
            backendProcess.StartInfo.FileName = foundPython;
            backendProcess.StartInfo.Arguments = "-u server/run_server.py";
            backendProcess.StartInfo.WorkingDirectory = rootDir;
            backendProcess.StartInfo.UseShellExecute = false;
            backendProcess.StartInfo.RedirectStandardOutput = true;
            backendProcess.StartInfo.RedirectStandardError = true;
            backendProcess.StartInfo.EnvironmentVariables["PYTHONUTF8"] = "1";
            backendProcess.StartInfo.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

            backendProcess.OutputDataReceived += (sender, args) =>
            {
                if (!string.IsNullOrEmpty(args.Data))
                    Console.WriteLine(args.Data);
            };
            backendProcess.ErrorDataReceived += (sender, args) =>
            {
                if (!string.IsNullOrEmpty(args.Data))
                    Console.Error.WriteLine(args.Data);
            };

            backendProcess.Start();
            backendProcess.BeginOutputReadLine();
            backendProcess.BeginErrorReadLine();

            var port = ReadPort(rootDir);
            var started = WaitForPort("127.0.0.1", port, 15000);

            var url = "http://localhost:" + port + "/";
            WriteStep("Open browser");
            Process.Start(new ProcessStartInfo
            {
                FileName = url,
                UseShellExecute = true
            });

            Console.WriteLine();
            Console.WriteLine("Project started: " + url);
            Console.WriteLine("Backend PID: " + backendProcess.Id);
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine();
            Console.Error.WriteLine("Launcher failed: " + ex.Message);
            Console.Error.WriteLine("Press any key to exit...");
            Console.ReadKey();
            return 1;
        }
    }

    private static void WriteStep(string message)
    {
        Console.WriteLine();
        Console.WriteLine("[{0}] {1}", DateTime.Now.ToString("HH:mm:ss"), message);
    }

    private static void EnsureFileExists(string path, string message)
    {
        if (!File.Exists(path))
            throw new FileNotFoundException(message, path);
    }

    private static void PrependPath(string path)
    {
        var currentPath = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        Environment.SetEnvironmentVariable("PATH", path + ";" + currentPath);
    }

    private static void StopOldBackend(string processName)
    {
        foreach (var process in Process.GetProcessesByName(processName))
        {
            try
            {
                process.Kill();
                process.WaitForExit(5000);
            }
            catch { }
        }
    }

    private static int ReadPort(string rootDir)
    {
        var configJson = Path.Combine(rootDir, "server", "Config.json");
        if (File.Exists(configJson))
        {
            var text = File.ReadAllText(configJson);
            var match = Regex.Match(text, "\"port\"\\s*:\\s*(\\d+)");
            int jsonPort;
            if (match.Success && int.TryParse(match.Groups[1].Value, out jsonPort))
                return jsonPort;
        }
        return 8080;
    }

    private static bool RequiresOllama(string configJsonPath)
    {
        if (!File.Exists(configJsonPath))
            return false;

        var text = File.ReadAllText(configJsonPath);
        var primaryIsOllama = Regex.IsMatch(text,
            "\"primary\"\\s*:\\s*\\{[\\s\\S]*?\"type\"\\s*:\\s*\"ollama\"",
            RegexOptions.IgnoreCase);

        var secondaryBlock = Regex.Match(text,
            "\"secondary\"\\s*:\\s*\\{([\\s\\S]*?)\\}",
            RegexOptions.IgnoreCase);
        var secondaryIsOllama = false;
        if (secondaryBlock.Success)
        {
            var secondaryText = secondaryBlock.Groups[1].Value;
            var enabled = Regex.IsMatch(secondaryText, "\"enabled\"\\s*:\\s*true", RegexOptions.IgnoreCase);
            var typeIsOllama = Regex.IsMatch(secondaryText, "\"type\"\\s*:\\s*\"ollama\"", RegexOptions.IgnoreCase);
            secondaryIsOllama = enabled && typeIsOllama;
        }

        return primaryIsOllama || secondaryIsOllama;
    }

    private static void EnsureOllamaRunning(string rootDir)
    {
        if (IsTcpPortOpen("127.0.0.1", 11434, 500))
        {
            Console.WriteLine("Ollama is already running.");
            return;
        }

        var ollamaExe = FindOllamaExe(rootDir);
        if (string.IsNullOrEmpty(ollamaExe) || !File.Exists(ollamaExe))
            throw new FileNotFoundException("Config requires Ollama, but ollama.exe was not found.");

        Console.WriteLine("Start Ollama: " + ollamaExe);
        var process = new Process();
        process.StartInfo.FileName = ollamaExe;
        process.StartInfo.Arguments = "serve";
        process.StartInfo.WorkingDirectory = Path.GetDirectoryName(ollamaExe);
        process.StartInfo.UseShellExecute = true;
        process.StartInfo.WindowStyle = ProcessWindowStyle.Minimized;
        process.Start();

        for (var i = 0; i < 20; i++)
        {
            System.Threading.Thread.Sleep(500);
            if (IsTcpPortOpen("127.0.0.1", 11434, 500))
            {
                Console.WriteLine("Ollama started.");
                return;
            }
        }

        throw new InvalidOperationException("Ollama did not start on port 11434.");
    }

    private static string FindPythonExe(string rootDir, string aiCoreDir)
    {
        // 1. 检查 conda 环境（用户开发环境）
        var condaPython = @"D:\anaconda_2024\envs\pytorch_gpu\python.exe";
        if (File.Exists(condaPython))
            return condaPython;
        // 自动检测其他 conda 环境
        string condaPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            "anaconda_2024", "envs");
        if (Directory.Exists(condaPath))
        {
            foreach (var envDir in Directory.GetDirectories(condaPath))
            {
                var candidate = Path.Combine(envDir, "python.exe");
                if (File.Exists(candidate))
                    return candidate;
            }
        }

        // 2. 检查项目 venv
        var venvPython = Path.Combine(aiCoreDir, "ai_diet_env", "Scripts", "python.exe");
        if (File.Exists(venvPython))
            return venvPython;

        // 3. 搜索 %LOCALAPPDATA%/Programs/Python
        var localPython = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "Python");
        if (Directory.Exists(localPython))
        {
            foreach (var dir in Directory.GetDirectories(localPython))
            {
                var candidate = Path.Combine(dir, "python.exe");
                if (File.Exists(candidate))
                    return candidate;
            }
        }

        // 4. 在 PATH 中查找 python.exe
        var fromPath = FindExecutableInPath("python.exe");
        if (!string.IsNullOrEmpty(fromPath))
            return fromPath;

        return string.Empty;
    }

    private static string FindOllamaExe(string rootDir)
    {
        var fromPath = FindExecutableInPath("ollama.exe");
        if (!string.IsNullOrEmpty(fromPath))
            return fromPath;

        var candidates = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Programs", "Ollama", "ollama.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                "Ollama", "ollama.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                "Ollama", "ollama.exe"),
            Path.Combine(rootDir, "Ollama", "ollama.exe")
        };

        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrEmpty(candidate) && File.Exists(candidate))
                return candidate;
        }

        return string.Empty;
    }

    private static string FindExecutableInPath(string fileName)
    {
        var pathValue = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        var parts = pathValue.Split(new[] { ';' }, StringSplitOptions.RemoveEmptyEntries);
        foreach (var rawPart in parts)
        {
            var part = rawPart.Trim();
            if (string.IsNullOrEmpty(part)) continue;
            try
            {
                var candidate = Path.Combine(part, fileName);
                if (File.Exists(candidate))
                    return candidate;
            }
            catch { }
        }
        return string.Empty;
    }

    private static bool IsTcpPortOpen(string host, int port, int timeoutMs)
    {
        TcpClient client = null;
        try
        {
            client = new TcpClient();
            var result = client.BeginConnect(host, port, null, null);
            var success = result.AsyncWaitHandle.WaitOne(timeoutMs);
            if (!success) return false;
            client.EndConnect(result);
            return true;
        }
        catch { return false; }
        finally
        {
            if (client != null) client.Close();
        }
    }

    private static bool WaitForPort(string host, int port, int timeoutMs)
    {
        var elapsed = 0;
        var interval = 500;
        while (elapsed < timeoutMs)
        {
            if (IsTcpPortOpen(host, port, 1000))
                return true;
            System.Threading.Thread.Sleep(interval);
            elapsed += interval;
        }
        throw new TimeoutException(
            string.Format("Backend did not start on port {0} within {1}s.", port, timeoutMs / 1000));
    }

    private static bool RunProcessCheck(string fileName, string arguments, string workingDirectory)
    {
        var process = new Process();
        process.StartInfo.FileName = fileName;
        process.StartInfo.Arguments = arguments;
        process.StartInfo.WorkingDirectory = workingDirectory;
        process.StartInfo.UseShellExecute = false;
        process.StartInfo.RedirectStandardOutput = true;
        process.StartInfo.RedirectStandardError = true;
        process.Start();
        if (!process.WaitForExit(10000))
        {
            process.Kill();
            return false;
        }
        return process.ExitCode == 0;
    }

    private static void RunProcess(string fileName, string arguments, string workingDirectory)
    {
        var process = new Process();
        process.StartInfo.FileName = fileName;
        process.StartInfo.Arguments = arguments;
        process.StartInfo.WorkingDirectory = workingDirectory;
        process.StartInfo.UseShellExecute = false;
        process.StartInfo.RedirectStandardOutput = true;
        process.StartInfo.RedirectStandardError = true;

        process.OutputDataReceived += (sender, args) =>
        {
            if (!string.IsNullOrEmpty(args.Data))
                Console.WriteLine(args.Data);
        };
        process.ErrorDataReceived += (sender, args) =>
        {
            if (!string.IsNullOrEmpty(args.Data))
                Console.Error.WriteLine(args.Data);
        };

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        if (!process.WaitForExit(300000))
        {
            process.Kill();
            throw new TimeoutException(
                string.Format("Process timed out (>5min): {0} {1}", fileName, arguments));
        }

        if (process.ExitCode != 0)
            throw new InvalidOperationException(
                string.Format("{0} exited with code {1}.", fileName, process.ExitCode));
    }
}
