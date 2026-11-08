import { fireEvent, screen, waitFor } from '@testing-library/react-native';
import * as IntentLauncher from 'expo-intent-launcher';
import * as Sharing from 'expo-sharing';
import type { ThreadMessage } from '../../src/api/types';
import { pickDocuments, pickPhotos, takePhoto } from '../../src/features/attachments/pick';
import type { PendingFile } from '../../src/features/attachments/rules';
import { NewTicketScreen } from '../../src/features/tickets/NewTicketScreen';
import { TicketDetailScreen } from '../../src/features/tickets/TicketDetailScreen';
import type { FakeReply, FakeRequest } from '../../test/fakeFetch';
import { detail, renderSignedIn } from '../../test/tickets';

// The native pickers are replaced; everything after them (rules, upload,
// download, open) is the real code.
jest.mock('../../src/features/attachments/pick', () => ({
  ...jest.requireActual('../../src/features/attachments/pick'),
  pickPhotos: jest.fn(),
  takePhoto: jest.fn(),
  pickDocuments: jest.fn(),
}));

const pending = (name: string, size = 2048): PendingFile => ({
  key: name,
  uri: `file:///cache/picked/${name}`,
  name,
  size,
  mimeType: null,
});
const picked = (...files: PendingFile[]) => ({ kind: 'picked' as const, files });

const CREATED = { ticket_id: 'TCK-new', message_id: 'M1', ticket_type: 'ticket', route: 'human', status: 'open', ai_response: null };
const posts = (calls: FakeRequest[], path: string) => calls.filter((c) => c.method === 'POST' && c.path === path);
const uploadedNames = (req: FakeRequest) => ((req.body as FormData).getAll('files') as File[]).map((f) => f.name);

type Handler = FakeReply | ((req: FakeRequest) => FakeReply);

async function newTicket(upload: Handler) {
  const onCreated = jest.fn();
  const r = await renderSignedIn(<NewTicketScreen onCreated={onCreated} />, {
    'POST /api/tickets': { body: CREATED },
    'POST /api/tickets/TCK-new/attachments': upload,
  });
  await screen.findByRole('radio', { name: 'Billing & payments' });
  await fireEvent.changeText(screen.getByLabelText('Subject'), 'Payslip blank');
  await fireEvent.changeText(screen.getByLabelText('Description'), 'The payslip page shows nothing.');
  return { ...r, onCreated };
}

describe('attachments in a new ticket', () => {
  it('adds photos, camera shots and files, refuses a .har with a reason, and removes one', async () => {
    (pickPhotos as jest.Mock).mockResolvedValue(picked(pending('screen.png')));
    (takePhoto as jest.Mock).mockResolvedValue(picked(pending('photo-1.jpg')));
    (pickDocuments as jest.Mock).mockResolvedValue(picked(pending('steps.pdf'), pending('session.har'), pending('app.log')));
    await newTicket({ body: [] });

    await fireEvent.press(screen.getByRole('button', { name: 'Photos' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Camera' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Files' }));
    expect(pickPhotos).toHaveBeenCalledWith(5);
    for (const name of ['screen.png', 'photo-1.jpg', 'steps.pdf', 'app.log']) {
      expect(screen.getByTestId(`pending-${name}`)).toBeOnTheScreen();
    }
    expect(screen.getByTestId('attachment-rejected')).toHaveTextContent(
      'session.har can\'t be attached: only PNG, JPG, PDF, TXT and LOG files are allowed.',
    );
    expect(screen.getByText('4 / 5')).toBeOnTheScreen();

    await fireEvent.press(screen.getByRole('button', { name: 'Remove steps.pdf' }));
    expect(screen.queryByTestId('pending-steps.pdf')).not.toBeOnTheScreen();
    expect(screen.getByText('3 / 5')).toBeOnTheScreen();
  });

  it('turns the source buttons off at five files', async () => {
    (pickDocuments as jest.Mock).mockResolvedValue(picked(...['a', 'b', 'c', 'd', 'e', 'f'].map((n) => pending(`${n}.txt`))));
    await newTicket({ body: [] });
    await fireEvent.press(screen.getByRole('button', { name: 'Files' }));
    expect(screen.getByTestId('attachment-rejected')).toHaveTextContent('f.txt wasn\'t added: at most 5 files per message.');
    expect(screen.getByRole('button', { name: 'Photos' })).toBeDisabled();
    expect(screen.getByText(/most files one message can carry/)).toBeOnTheScreen();
  });

  it('explains a refused camera permission', async () => {
    (takePhoto as jest.Mock).mockResolvedValue({ kind: 'denied' });
    await newTicket({ body: [] });
    await fireEvent.press(screen.getByRole('button', { name: 'Camera' }));
    expect(screen.getByText('Camera access is off for this app.')).toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Open settings to allow it' })).toBeOnTheScreen();
  });

  it('creates the ticket, then uploads its files to the first message', async () => {
    (pickDocuments as jest.Mock).mockResolvedValue(picked(pending('steps.pdf'), pending('app.log')));
    const { calls, onCreated } = await newTicket({ body: [] });
    await fireEvent.press(screen.getByRole('button', { name: 'Files' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Submit ticket' }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(CREATED));
    const [upload] = posts(calls, '/api/tickets/TCK-new/attachments');
    expect((upload.body as FormData).get('message_id')).toBe('M1');
    expect(uploadedNames(upload)).toEqual(['steps.pdf', 'app.log']);
  });

  it('when the upload fails, keeps the ticket and retries only the upload', async () => {
    (pickDocuments as jest.Mock).mockResolvedValue(picked(pending('notes.txt'), pending('fake.pdf')));
    let uploads = 0;
    const { calls, onCreated } = await newTicket(() => {
      uploads += 1;
      return uploads === 1
        ? { status: 400, body: { detail: "fake.pdf doesn't look like a PDF file" } }
        : { body: [] };
    });
    await fireEvent.press(screen.getByRole('button', { name: 'Files' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Submit ticket' }));

    expect(await screen.findByTestId('upload-error')).toHaveTextContent(
      "Ticket TCK-new was created, but the files didn't upload: fake.pdf doesn't look like a PDF file",
    );
    expect(onCreated).not.toHaveBeenCalled();
    // The ticket's text is locked now; only the files can change.
    expect(screen.getByLabelText('Subject').props.editable).toBe(false);
    expect(screen.getByLabelText('Description').props.editable).toBe(false);
    await fireEvent.press(screen.getByRole('button', { name: 'Remove fake.pdf' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Retry upload' }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(CREATED));

    expect(posts(calls, '/api/tickets')).toHaveLength(1);
    const uploadCalls = posts(calls, '/api/tickets/TCK-new/attachments');
    expect(uploadCalls).toHaveLength(2);
    expect(uploadedNames(uploadCalls[1])).toEqual(['notes.txt']);
  });

  it('can open the ticket without the files after a failed upload', async () => {
    (pickPhotos as jest.Mock).mockResolvedValue(picked(pending('screen.png')));
    const { onCreated } = await newTicket({ status: 503, body: { detail: 'busy' } });
    await fireEvent.press(screen.getByRole('button', { name: 'Photos' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Submit ticket' }));
    await screen.findByTestId('upload-error');
    await fireEvent.press(screen.getByRole('button', { name: 'Open the ticket without these files' }));
    expect(onCreated).toHaveBeenCalledWith(CREATED);
  });
});

const PATH = '/api/tickets/TCK-00000001';

function staffReplyWithFile(): ThreadMessage {
  return {
    message_id: 'M9',
    sender: 'staff',
    sender_name: 'Ravi Kumar',
    sender_role: 'Support Agent',
    to: 'Asha Rao',
    subject: null,
    incident_update: false,
    message: 'Here is the corrected payslip.',
    created_at: '2026-11-06T10:00:00+00:00',
    attachments: [{ attachment_id: 'ATT-7', filename: 'payslip.pdf', content_type: 'application/pdf', size_bytes: 5 }],
  };
}

async function thread(routes: Record<string, Handler> = {}) {
  const base = detail();
  base.messages.push(staffReplyWithFile());
  let loads = 0;
  const r = await renderSignedIn(<TicketDetailScreen ticketId="TCK-00000001" />, {
    [`GET ${PATH}`]: () => {
      loads += 1;
      return { body: base };
    },
    ...routes,
  });
  await screen.findByText('Here is the corrected payslip.');
  return { ...r, loads: () => loads };
}

describe('attachments in a ticket thread', () => {
  it("downloads a staff reply's file with the token and opens it", async () => {
    const { calls } = await thread({
      [`GET ${PATH}/attachments/ATT-7`]: { bytes: new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d]) },
    });
    await fireEvent.press(screen.getByRole('button', { name: 'Open payslip.pdf' }));
    await waitFor(() => expect((Sharing.shareAsync as jest.Mock).mock.calls.length + (IntentLauncher.startActivityAsync as jest.Mock).mock.calls.length).toBe(1));
    const download = calls.find((c) => c.path.endsWith('/attachments/ATT-7'))!;
    expect(download.headers.Authorization).toBe('Bearer tok');
  });

  it('says why a file could not be opened', async () => {
    await thread({ [`GET ${PATH}/attachments/ATT-7`]: { status: 404, body: { detail: 'Attachment file is missing' } } });
    await fireEvent.press(screen.getByRole('button', { name: 'Open payslip.pdf' }));
    expect(await screen.findByTestId('attachment-error')).toHaveTextContent(/Couldn't open payslip.pdf/);
  });

  it('sends a reply with files, and on a failed upload retries the upload, not the reply', async () => {
    (pickDocuments as jest.Mock).mockResolvedValue(picked(pending('error.log')));
    let uploads = 0;
    const { calls, loads } = await thread({
      [`POST ${PATH}/reply`]: { body: { route: 'human', status: 'open', message_id: 'M10' } },
      [`POST ${PATH}/attachments`]: () => {
        uploads += 1;
        return uploads === 1 ? { status: 503, body: { detail: 'busy' } } : { body: [] };
      },
    });
    await fireEvent.changeText(screen.getByLabelText('Reply'), 'Log attached');
    await fireEvent.press(screen.getByRole('button', { name: 'Files' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByTestId('upload-error')).toHaveTextContent(/^Your reply was sent, but the files didn't upload: The help desk is busy/);
    // The reply shows in the thread already.
    expect(loads()).toBe(2);
    await fireEvent.press(screen.getByRole('button', { name: 'Retry upload' }));
    await waitFor(() => expect(screen.queryByTestId('upload-error')).not.toBeOnTheScreen());
    expect(screen.queryByTestId('pending-error.log')).not.toBeOnTheScreen();

    expect(posts(calls, `${PATH}/reply`)).toHaveLength(1);
    const uploadCalls = posts(calls, `${PATH}/attachments`);
    expect(uploadCalls).toHaveLength(2);
    expect((uploadCalls[1].body as FormData).get('message_id')).toBe('M10');
    expect(uploadedNames(uploadCalls[1])).toEqual(['error.log']);
  });

  it('can discard files that would not upload', async () => {
    (pickPhotos as jest.Mock).mockResolvedValue(picked(pending('screen.png')));
    await thread({
      [`POST ${PATH}/reply`]: { body: { route: 'human', status: 'open', message_id: 'M10' } },
      [`POST ${PATH}/attachments`]: { status: 400, body: { detail: "screen.png doesn't look like a PNG file" } },
    });
    await fireEvent.changeText(screen.getByLabelText('Reply'), 'Screenshot');
    await fireEvent.press(screen.getByRole('button', { name: 'Photos' }));
    await fireEvent.press(screen.getByRole('button', { name: 'Send' }));
    expect(await screen.findByTestId('upload-error')).toHaveTextContent(/doesn't look like a PNG file/);
    expect(screen.getByText('Remove or replace the file it names, then retry.')).toBeOnTheScreen();
    await fireEvent.press(screen.getByRole('button', { name: 'Discard these files' }));
    expect(screen.queryByTestId('upload-error')).not.toBeOnTheScreen();
    expect(screen.getByRole('button', { name: 'Send' })).toBeOnTheScreen();
  });
});
