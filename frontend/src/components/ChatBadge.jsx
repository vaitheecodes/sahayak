/* A plain outlined "Chat" mark for tickets that started as an AI chat
 * (escalated chats), next to their id. */
export function ChatBadge() {
  return (
    <span className="inline-flex h-5 items-center rounded-full border border-input px-2 text-xs font-medium text-muted-fg">
      Chat
    </span>
  );
}
