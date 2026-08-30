import {
  applyControllerUpdate,
  fetchControllerVersion,
  sameControllerVersion,
} from './controllerUpdate'

describe('applyControllerUpdate', () => {
  it('uses the validated HTTPS controller origin and paired bearer token', async () => {
    const fetchUpdate = jest.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          message: '更新已下載。',
          version: 'v0.3.0',
          restart_required: true,
        }),
        { status: 200 },
      ),
    )

    const result = await applyControllerUpdate(
      '192.168.1.42',
      8765,
      'paired-token',
      fetchUpdate,
    )

    expect(fetchUpdate).toHaveBeenCalledWith(
      'https://192.168.1.42:8765/api/update/apply',
      {
        method: 'POST',
        headers: {
          Authorization: 'Bearer paired-token',
          Origin: 'https://192.168.1.42:8765',
        },
      },
    )
    expect(result).toEqual({
      success: true,
      message: '更新已下載。',
      version: 'v0.3.0',
      restartRequired: true,
    })
  })

  it('surfaces the server detail when staging fails', async () => {
    const fetchUpdate = jest.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: '更新檔驗證失敗。' }), { status: 422 }),
    )

    await expect(
      applyControllerUpdate('tv.example.com', 443, 'paired-token', fetchUpdate),
    ).rejects.toThrow('更新檔驗證失敗。')
  })

  it('returns a friendly error for a non-JSON proxy response', async () => {
    const fetchUpdate = jest
      .fn()
      .mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 }))

    await expect(
      applyControllerUpdate('tv.example.com', 443, 'paired-token', fetchUpdate),
    ).rejects.toThrow('更新服務暫時無法使用（HTTP 502）。')
  })

  it('normalizes network and certificate failures', async () => {
    const fetchUpdate = jest.fn().mockRejectedValue(new TypeError('Network request failed'))

    await expect(
      applyControllerUpdate('tv.example.com', 443, 'paired-token', fetchUpdate),
    ).rejects.toThrow('無法連上電視盒，請確認 HTTPS 憑證與網路連線。')
  })

  it('reads the installed version after reconnect and normalizes a v prefix', async () => {
    const fetchHealth = jest.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', version: '0.4.0' }), { status: 200 }),
    )

    await expect(fetchControllerVersion('tv.example.com', 443, fetchHealth)).resolves.toBe(
      '0.4.0',
    )
    expect(fetchHealth).toHaveBeenCalledWith('https://tv.example.com/api/health', {
      method: 'GET',
    })
    expect(sameControllerVersion('v0.4.0', '0.4.0')).toBe(true)
  })
})
