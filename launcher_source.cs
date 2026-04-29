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
            var rootDir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var demoDir = Path.Combine(rootDir, "Demo");
            var buildDir = Path.Combine(demoDir, "build");
            var backendExe = Path.Combine(buildDir, "Debug", "backend.exe");
            var venvPython = Path.Combine(rootDir, "AI_Demo", "ai_diet_env", "Scripts", "python.exe");
            var venvScripts = Path.Combine(rootDir, "AI_Demo", "ai_diet_env", "Scripts");

            WriteStep("Check project files");
            EnsureFileExists(Path.Combine(demoDir, "backend.cpp"), "Demo\\backend.cpp not found. Put the launcher exe in the project root.");

            WriteStep("Stop old backend");
            StopOldBackend(backendExe);

            WriteStep("Prepare Python");
            if (File.Exists(venvPython))
            {
                PrependPath(venvScripts);
                Console.WriteLine("Use venv Python: " + venvPython);
            }
            else
            {
                Console.WriteLine("Venv Python not found. Use system Python.");
            }

            var configJsonPath = Path.Combine(demoDir, "Config.json");
            var needOllama = RequiresOllama(configJsonPath);
            if (needOllama)
            {
                WriteStep("Check Ollama");
                EnsureOllamaRunning(rootDir);
            }

            WriteStep("Build backend");
            if (!Directory.Exists(buildDir))
            {
                Directory.CreateDirectory(buildDir);
            }

            if (!File.Exists(Path.Combine(buildDir, "CMakeCache.txt")))
            {
                RunProcess("cmake", "-S \"" + demoDir + "\" -B \"" + buildDir + "\"", rootDir);
            }

            RunProcess("cmake", "--build \"" + buildDir + "\" --config Debug", rootDir);
            EnsureFileExists(backendExe, "Build finished but backend.exe was not found.");

            WriteStep("Start backend");
            var backendProcess = new Process();
            backendProcess.StartInfo.FileName = backendExe;
            backendProcess.StartInfo.WorkingDirectory = buildDir;
            backendProcess.StartInfo.UseShellExecute = true;
            backendProcess.StartInfo.WindowStyle = ProcessWindowStyle.Minimized;
            backendProcess.Start();

            System.Threading.Thread.Sleep(2000);

            var port = ReadPort(rootDir);
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
        {
            throw new FileNotFoundException(message, path);
        }
    }

    private static void PrependPath(string path)
    {
        var currentPath = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        Environment.SetEnvironmentVariable("PATH", path + ";" + currentPath);
    }

    private static void StopOldBackend(string backendExe)
    {
        var target = Path.GetFullPath(backendExe);
        foreach (var process in Process.GetProcessesByName("backend"))
        {
            try
            {
                var processPath = process.MainModule != null ? process.MainModule.FileName : string.Empty;
                if (string.IsNullOrEmpty(processPath))
                {
                    continue;
                }

                if (string.Equals(Path.GetFullPath(processPath), target, StringComparison.OrdinalIgnoreCase))
                {
                    process.Kill();
                    process.WaitForExit(5000);
                }
            }
            catch
            {
                // Ignore unrelated or protected processes.
            }
        }
    }

    private static int ReadPort(string rootDir)
    {
        var configJson = Path.Combine(rootDir, "Demo", "Config.json");
        if (File.Exists(configJson))
        {
            var text = File.ReadAllText(configJson);
            var match = Regex.Match(text, "\"port\"\\s*:\\s*(\\d+)");
            int jsonPort;
            if (match.Success && int.TryParse(match.Groups[1].Value, out jsonPort))
            {
                return jsonPort;
            }
        }

        var configTxt = Path.Combine(rootDir, "Demo", "config.txt");
        if (File.Exists(configTxt))
        {
            foreach (var line in File.ReadAllLines(configTxt))
            {
                var match = Regex.Match(line, "^\\s*port\\s*=\\s*(\\d+)\\s*$");
                int textPort;
                if (match.Success && int.TryParse(match.Groups[1].Value, out textPort))
                {
                    return textPort;
                }
            }
        }

        return 8080;
    }

    private static bool RequiresOllama(string configJsonPath)
    {
        if (!File.Exists(configJsonPath))
        {
            return false;
        }

        var text = File.ReadAllText(configJsonPath);
        var primaryIsOllama = Regex.IsMatch(
            text,
            "\"primary\"\\s*:\\s*\\{[\\s\\S]*?\"type\"\\s*:\\s*\"ollama\"",
            RegexOptions.IgnoreCase
        );

        var secondaryBlock = Regex.Match(
            text,
            "\"secondary\"\\s*:\\s*\\{([\\s\\S]*?)\\}",
            RegexOptions.IgnoreCase
        );
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
        {
            throw new FileNotFoundException("Config requires Ollama, but ollama.exe was not found.");
        }

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

    private static string FindOllamaExe(string rootDir)
    {
        var fromPath = FindExecutableInPath("ollama.exe");
        if (!string.IsNullOrEmpty(fromPath))
        {
            return fromPath;
        }

        var candidates = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Ollama", "ollama.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Ollama", "ollama.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Ollama", "ollama.exe"),
            Path.Combine(rootDir, "Ollama", "ollama.exe")
        };

        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrEmpty(candidate) && File.Exists(candidate))
            {
                return candidate;
            }
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
            if (string.IsNullOrEmpty(part))
            {
                continue;
            }

            try
            {
                var candidate = Path.Combine(part, fileName);
                if (File.Exists(candidate))
                {
                    return candidate;
                }
            }
            catch
            {
                // Ignore invalid PATH entries.
            }
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
            if (!success)
            {
                return false;
            }

            client.EndConnect(result);
            return true;
        }
        catch
        {
            return false;
        }
        finally
        {
            if (client != null)
            {
                client.Close();
            }
        }
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
            {
                Console.WriteLine(args.Data);
            }
        };
        process.ErrorDataReceived += (sender, args) =>
        {
            if (!string.IsNullOrEmpty(args.Data))
            {
                Console.Error.WriteLine(args.Data);
            }
        };

        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        process.WaitForExit();

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException(fileName + " exited with code " + process.ExitCode + ".");
        }
    }
}
