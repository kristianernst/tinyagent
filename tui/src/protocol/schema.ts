import schema from "./schema.generated.json";

export const surfaceSchema = schema;

export function schemaVersion(): number {
  return Number((surfaceSchema as { schema_version?: number }).schema_version ?? 0);
}
