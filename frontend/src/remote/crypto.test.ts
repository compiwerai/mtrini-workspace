// @vitest-environment node
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { newKeyPair, Opener, pairingCode, seal, sharedKey } from './crypto';

const BACKEND = path.resolve(__dirname, '../../../backend');

// Runs a Python snippet with mtrini.remote_crypto (the desktop side) and returns its JSON output.
function py(code: string, input: object): any {
  const out = execFileSync('python', ['-c', `import json,sys\nfrom mtrini.remote_crypto import *\nI=json.load(sys.stdin)\n${code}`],
    { input: JSON.stringify(input), env: { ...process.env, PYTHONPATH: BACKEND } });
  return JSON.parse(out.toString());
}

describe('bridge encryption: phone (Web Crypto) and PC (Python) agree', () => {
  it('pairing code, shared key and messages work across both implementations', async () => {
    const pc = py('k=new_private_key(); print(json.dumps({"priv": private_to_str(k), "pub": public_str(k)}))', {});
    const phone = await newKeyPair();
    const jsCode = await pairingCode(pc.pub, phone.pub);
    expect(jsCode).toMatch(/^\d{6}$/);

    const fromPc = py(`k=private_from_str(I["priv"])
key=shared_key(k, I["phone"], I["pub"], I["phone"])
print(json.dumps({"code": pairing_code(I["pub"], I["phone"]), "box": seal(key, "pc1", "ph1", {"kind": "res", "body": "héllo"})}))`,
    { priv: pc.priv, pub: pc.pub, phone: phone.pub });
    expect(fromPc.code).toBe(jsCode);

    const key = await sharedKey(phone, pc.pub, pc.pub, phone.pub);
    const opener = new Opener(key, 'pc1', 'ph1');
    const msg = await opener.open(fromPc.box);
    expect(msg.kind).toBe('res');
    expect(msg.body).toBe('héllo');
    await expect(opener.open(fromPc.box)).rejects.toThrow(/replayed/);
    // bound to sender > receiver: the same box can't be passed off as coming the other way
    await expect(new Opener(key, 'ph1', 'pc1').open(fromPc.box)).rejects.toThrow();

    const toPc = await seal(key, 'ph1', 'pc1', { kind: 'req', path: '/api/threads' });
    const opened = py(`k=private_from_str(I["priv"])
key=shared_key(k, I["phone"], I["pub"], I["phone"])
print(json.dumps(Opener(key, "ph1", "pc1").open(I["box"])))`, { priv: pc.priv, pub: pc.pub, phone: phone.pub, box: toPc });
    expect(opened.path).toBe('/api/threads');
  });

  it('a swapped key changes the pairing code', async () => {
    const pc = await newKeyPair(), phone = await newKeyPair(), attacker = await newKeyPair();
    expect(await pairingCode(pc.pub, phone.pub)).not.toBe(await pairingCode(attacker.pub, phone.pub));
  });
});
