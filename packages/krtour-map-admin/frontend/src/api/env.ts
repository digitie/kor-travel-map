export function publicUrlEnv(
  value: string | undefined,
  name: string,
  developmentFallback: string,
): string {
  if (value !== undefined && value.length > 0) {
    return value;
  }
  if (process.env.NODE_ENV === "production") {
    throw new Error(`${name} is required in production`);
  }
  return developmentFallback;
}
