import { useTranslation } from 'react-i18next';
import { MessageCircle } from 'lucide-react-native';
import { useTheme } from '../../src/theme/ThemeProvider';
import { EmptyState } from '../../src/ui/EmptyState';
import { Screen } from '../../src/ui/Screen';

// Stage 3 replaces this with the support chat.
export default function ChatTab() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  return (
    <Screen scroll={false} edges={[]}>
      <EmptyState
        icon={<MessageCircle size={32} color={colors.mutedFg} />}
        title={t('placeholder.chatTitle')}
        body={t('placeholder.chatBody')}
      />
    </Screen>
  );
}
