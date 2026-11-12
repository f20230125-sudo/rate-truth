import { MoneySchema } from "./schema";
export function formatMoney(value: string): string {
  const valid = MoneySchema.parse(value);
  const [whole, decimal] = valid.split(".");
  return `AED ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${decimal}`;
}
