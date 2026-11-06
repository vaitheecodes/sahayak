import { useState } from 'react';
import { router, useLocalSearchParams } from 'expo-router';
import { useHeaderHeight } from 'expo-router/react-navigation';
import { ChatSessionScreen } from '../../src/features/chat/ChatSessionScreen';
import { takePrimedChat } from '../../src/features/chat/chatCache';

export default function ChatRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const headerHeight = useHeaderHeight();
  const [initial] = useState(() => takePrimedChat(id));
  return (
    <ChatSessionScreen
      sessionId={id}
      initial={initial}
      keyboardOffset={headerHeight}
      onOpenTicket={(ticketId) => router.push({ pathname: '/tickets/[id]', params: { id: ticketId } })}
      onNewChat={() => router.back()}
    />
  );
}
