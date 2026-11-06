import { Stack, useLocalSearchParams } from 'expo-router';
import { TicketDetailScreen } from '../../src/features/tickets/TicketDetailScreen';

export default function TicketDetailRoute() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return (
    <>
      <Stack.Screen options={{ title: id }} />
      <TicketDetailScreen ticketId={id} />
    </>
  );
}
