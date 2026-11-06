import { router } from 'expo-router';
import { ChatHomeScreen } from '../../src/features/chat/ChatHomeScreen';
import { primeChat } from '../../src/features/chat/chatCache';

export default function ChatTab() {
  return (
    <ChatHomeScreen
      onStarted={(session) => {
        primeChat(session);
        router.push({ pathname: '/chats/[id]', params: { id: session.session_id } });
      }}
      onOpen={(id) => router.push({ pathname: '/chats/[id]', params: { id } })}
    />
  );
}
