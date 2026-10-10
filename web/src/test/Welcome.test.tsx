import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { ApiError, api } from '../api';
import { SessionProvider } from '../session';

const session = {
  user: { id: 'user-1', username: 'tester', role: 'user' as const, must_change_password: false },
  csrf_token: 'test-only',
};
beforeEach(() => {
  vi.spyOn(api, 'list').mockResolvedValue({ items: [] });
});
function mount() {
  return render(
    <MemoryRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </MemoryRouter>,
  );
}

describe('research submission', () => {
  it('keeps the question through login and waits for explicit submission afterward', async () => {
    vi.spyOn(api, 'me').mockRejectedValue(new ApiError(401, 'AUTH_REQUIRED', '请登录'));
    vi.spyOn(api, 'login').mockResolvedValue(session);
    const create = vi.spyOn(api, 'create');
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText('研究主题'), '比较两种储能技术');
    await user.click(screen.getByRole('button', { name: '开始研究' }));
    await user.type(await screen.findByLabelText('账号'), 'tester');
    await user.type(screen.getByLabelText('密码'), 'a-test-password');
    await user.click(screen.getByRole('button', { name: '登录' }));
    expect(await screen.findByLabelText('研究主题')).toHaveValue('比较两种储能技术');
    expect(create).not.toHaveBeenCalled();
  });
  it('preserves input and reuses the same idempotency key after an uncertain network failure', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(session);
    const create = vi
      .spyOn(api, 'create')
      .mockRejectedValue(new ApiError(0, 'NETWORK_ERROR', '网络连接中断'));
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText('研究主题'), '低功耗芯片发展');
    await user.click(screen.getByRole('button', { name: '开始研究' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('网络连接中断');
    expect(screen.getByLabelText('研究主题')).toHaveValue('低功耗芯片发展');
    await user.click(screen.getByRole('button', { name: '开始研究' }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(2));
    expect(create.mock.calls[0][1]).toBe(create.mock.calls[1][1]);
    await user.type(screen.getByLabelText('研究主题'), '与应用');
    await user.click(screen.getByRole('button', { name: '开始研究' }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(3));
    expect(create.mock.calls[2][1]).not.toBe(create.mock.calls[1][1]);
  });
  it('preserves guest input through the required first password change without creating a task', async () => {
    vi.spyOn(api, 'me').mockRejectedValue(new ApiError(401, 'AUTH_REQUIRED', '请登录'));
    vi.spyOn(api, 'login').mockResolvedValue({
      ...session,
      user: { ...session.user, must_change_password: true },
    });
    vi.spyOn(api, 'changePassword').mockResolvedValue(session);
    const create = vi.spyOn(api, 'create');
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText('研究主题'), '需要保留的研究主题');
    await user.click(screen.getByRole('button', { name: '开始研究' }));
    await user.type(await screen.findByLabelText('账号'), 'tester');
    await user.type(screen.getByLabelText('密码'), 'initial-password');
    await user.click(screen.getByRole('button', { name: '登录' }));
    await user.type(await screen.findByLabelText('当前密码'), 'initial-password');
    await user.type(screen.getByLabelText(/^新密码/), 'personal-password');
    await user.type(screen.getByLabelText('再次输入新密码'), 'personal-password');
    await user.click(screen.getByRole('button', { name: '保存新密码' }));
    expect(await screen.findByLabelText('研究主题')).toHaveValue('需要保留的研究主题');
    expect(create).not.toHaveBeenCalled();
  });
  it('allows Enter and IME composition without submitting', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(session);
    const create = vi.spyOn(api, 'create');
    const user = userEvent.setup();
    mount();
    await user.type(screen.getByLabelText('研究主题'), '行业研究{Enter}补充范围');
    expect(screen.getByLabelText('研究主题')).toHaveValue('行业研究\n补充范围');
    expect(create).not.toHaveBeenCalled();
  });
});
