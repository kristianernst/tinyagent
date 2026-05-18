#!/usr/bin/env bun
import { runApp, type AppOptions } from "./app";

const options = parseArgs(process.argv.slice(2));
runApp(options).then(
  (code) => {
    process.exitCode = code;
  },
  (error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  },
);

function parseArgs(argv: string[]): AppOptions {
  const options: AppOptions = {};
  const task: string[] = [];
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--server") options.server = take(argv, ++index, "--server");
    else if (arg === "--workspace") options.workspace = take(argv, ++index, "--workspace");
    else if (arg === "--provider") options.provider = take(argv, ++index, "--provider");
    else if (arg === "--model") options.model = take(argv, ++index, "--model");
    else if (arg === "--profile") options.profile = take(argv, ++index, "--profile");
    else if (arg === "--approval-mode") options.approvalMode = take(argv, ++index, "--approval-mode");
    else if (arg === "--task") task.push(take(argv, ++index, "--task"));
    else task.push(arg);
  }
  options.task = task.join(" ").trim() || undefined;
  return options;
}

function take(argv: string[], index: number, flag: string): string {
  const value = argv[index];
  if (!value) throw new Error(`${flag} requires a value`);
  return value;
}
