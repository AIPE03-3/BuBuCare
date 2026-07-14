import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getEventById } from '../api/events';
import { StatusTag } from '../components/StatusTag';
import { formatTime } from '../utils/time';
import type { CareEvent } from '../types';

function BackButton() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate(-1)}
      className="self-start rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-sm text-[var(--brand)] transition-colors duration-150"
    >
      ‹ 返回上一頁
    </button>
  );
}

export function EventDetail() {
  const { id } = useParams();
  const [event, setEvent] = useState<CareEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!id) return;
    getEventById(id).then((result) => {
      setEvent(result);
      setNow(Date.now());
      setLoading(false);
    });
  }, [id]);

  if (loading) {
    return <p className="text-sm text-[var(--text-secondary)]">載入中...</p>;
  }

  if (!event) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">找不到此事件</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">事件詳情 #{event.id}</h1>
      <p className="text-sm text-[var(--text-primary)]">
        跌倒　{event.camera.zone}（{event.camera.name}）
      </p>
      <div className="flex items-center gap-2">
        <StatusTag status={event.status} ackDeadline={event.ack_deadline} now={now} />
        {event.assignee && <span className="text-sm text-[var(--text-primary)]">已接手 {event.assignee}</span>}
      </div>
      <p className="text-sm text-[var(--text-secondary)]">發生時間：{formatTime(event.occurred_at)}</p>
    </div>
  );
}

export default EventDetail;
