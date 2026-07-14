import type { CareEvent } from '../types';

export function hasEscalatedFlag(event: CareEvent): boolean {
  return event.alerted_at !== null || event.escalated_to !== null;
}
