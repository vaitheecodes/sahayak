import { Tabs, router } from 'expo-router';
import { useTranslation } from 'react-i18next';
import { MessageCircle, Inbox, Plus, UserRound } from 'lucide-react-native';
import { HeaderTextButton } from '../../src/ui/HeaderTextButton';
import { useTheme } from '../../src/theme/ThemeProvider';
import { fonts } from '../../src/theme/tokens';

export default function TabsLayout() {
  const { t } = useTranslation();
  const { colors } = useTheme();
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.sheet },
        headerTintColor: colors.fg,
        headerTitleStyle: { fontFamily: fonts.semibold, fontSize: 17 },
        headerShadowVisible: false,
        sceneStyle: { backgroundColor: colors.frame },
        tabBarStyle: { backgroundColor: colors.sheet, borderTopColor: colors.border },
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.mutedFg,
        tabBarLabelStyle: { fontFamily: fonts.medium, fontSize: 12 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: t('tabs.chat'),
          tabBarIcon: ({ color, size }) => <MessageCircle color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="tickets"
        options={{
          title: t('tabs.tickets'),
          headerRight: () => (
            <HeaderTextButton
              label={t('tickets.newShort')}
              accessibilityLabel={t('tickets.new')}
              icon={<Plus size={18} color={colors.primary} />}
              onPress={() => router.push('/tickets/new')}
            />
          ),
          tabBarIcon: ({ color, size }) => <Inbox color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="account"
        options={{
          title: t('tabs.account'),
          tabBarIcon: ({ color, size }) => <UserRound color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
