import { useNavigate } from 'react-router-dom';

// 全站共用返回鍵：無外框、text-link 樣式，返回瀏覽器上一頁。
export function BackButton() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate(-1)}
      className="self-start rounded-md px-2 py-1 text-sm text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
    >
      ‹ 返回上一頁
    </button>
  );
}

export default BackButton;
