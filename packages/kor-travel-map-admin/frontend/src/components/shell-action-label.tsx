import type { ReactNode } from "react";

/**
 * 관리자 셸 상단 바 동작 버튼의 라벨. md 미만에서는 시각적으로 숨겨 아이콘 버튼이 되고
 * 접근성 이름은 그대로 남는다(상단 바는 한 줄이라 좁은 폭에서 텍스트 버튼이 제목을 밀어낸다).
 * 아이콘 없이 쓰면 좁은 폭에서 빈 버튼이 되므로 반드시 `data-icon` 아이콘과 함께 쓴다.
 */
export function ShellActionLabel({ children }: { children: ReactNode }) {
  return (
    <span data-slot="shell-action-label" className="max-md:sr-only">
      {children}
    </span>
  );
}
