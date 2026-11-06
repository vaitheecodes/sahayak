import '../src/i18n';
import { useEffect } from 'react';
import { Platform } from 'react-native';
import { useTranslation } from 'react-i18next';
import { Stack, router } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useFonts } from 'expo-font';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { IBMPlexSans_400Regular } from '@expo-google-fonts/ibm-plex-sans/400Regular';
import { IBMPlexSans_500Medium } from '@expo-google-fonts/ibm-plex-sans/500Medium';
import { IBMPlexSans_600SemiBold } from '@expo-google-fonts/ibm-plex-sans/600SemiBold';
import { apiConfig } from '../src/config';
import { SessionProvider, useSession } from '../src/auth/SessionProvider';
import { ThemeProvider, useTheme } from '../src/theme/ThemeProvider';
import { ConfigErrorScreen } from '../src/features/auth/StatusScreens';
import { MetaProvider } from '../src/features/meta/MetaProvider';
import { HeaderTextButton } from '../src/ui/HeaderTextButton';

SplashScreen.preventAutoHideAsync().catch(() => undefined);

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts({
    IBMPlexSans_400Regular,
    IBMPlexSans_500Medium,
    IBMPlexSans_600SemiBold,
  });
  const fontsReady = fontsLoaded || !!fontError;

  return (
    <SafeAreaProvider>
      <ThemeProvider>
        {apiConfig.ok ? (
          <SessionProvider baseUrl={apiConfig.url}>
            <Navigator fontsReady={fontsReady} />
          </SessionProvider>
        ) : (
          <ConfigOnly fontsReady={fontsReady} />
        )}
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

function ConfigOnly({ fontsReady }: { fontsReady: boolean }) {
  useEffect(() => {
    if (fontsReady) SplashScreen.hideAsync().catch(() => undefined);
  }, [fontsReady]);
  if (!fontsReady) return null;
  return <ConfigErrorScreen />;
}

function Navigator({ fontsReady }: { fontsReady: boolean }) {
  const { status, user } = useSession();
  const { colors, scheme } = useTheme();
  const { t } = useTranslation();
  const ready = fontsReady && status !== 'loading';

  useEffect(() => {
    if (ready) SplashScreen.hideAsync().catch(() => undefined);
  }, [ready]);

  if (!ready) return null;

  const signedIn = status === 'signedIn' && !!user;
  const mustChange = signedIn && user!.must_change_password;

  return (
    <MetaProvider>
      <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: colors.frame },
          headerStyle: { backgroundColor: colors.sheet },
          headerTintColor: colors.fg,
          headerTitleStyle: { fontFamily: 'IBMPlexSans_600SemiBold' },
          headerShadowVisible: false,
        }}
      >
        <Stack.Protected guard={status === 'signedOut'}>
          <Stack.Screen name="sign-in" />
        </Stack.Protected>
        <Stack.Protected guard={status === 'unreachable'}>
          <Stack.Screen name="offline" />
        </Stack.Protected>
        <Stack.Protected guard={mustChange}>
          <Stack.Screen name="change-password" />
        </Stack.Protected>
        <Stack.Protected guard={signedIn && !mustChange}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="password" options={{ headerShown: true, title: '', presentation: 'modal' }} />
          <Stack.Screen
            name="chats/[id]"
            options={{ headerShown: true, title: t('chat.title'), headerBackTitle: t('tabs.chat') }}
          />
          <Stack.Screen
            name="tickets/[id]"
            options={{ headerShown: true, title: '', headerBackTitle: t('tabs.tickets') }}
          />
          <Stack.Screen
            name="tickets/new"
            options={{
              headerShown: true,
              title: t('newTicket.title'),
              presentation: 'modal',
              // An iOS sheet has no back button; Android keeps its back arrow.
              headerLeft:
                Platform.OS === 'ios'
                  ? () => <HeaderTextButton label={t('common.cancel')} onPress={() => router.back()} />
                  : undefined,
            }}
          />
        </Stack.Protected>
      </Stack>
    </MetaProvider>
  );
}
