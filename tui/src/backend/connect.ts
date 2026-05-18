import { TinyAgentClient } from "./client";

export async function connectBackend(server: string): Promise<TinyAgentClient> {
  const client = new TinyAgentClient(server);
  const health = await client.health();
  if (!health.healthy) throw new Error(`backend is unhealthy: ${server}`);
  if (health.schema_version !== 1) throw new Error(`unsupported schema version: ${health.schema_version}`);
  return client;
}
