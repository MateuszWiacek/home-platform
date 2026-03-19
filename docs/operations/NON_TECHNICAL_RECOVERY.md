# Non-Technical Recovery

If something stopped working and the maintainer is not around, try these steps in order.
No terminal needed.

---

## Step 1: Check the dashboard

Open [https://home.homelab.local](https://home.homelab.local) in your browser.
If it loads, you can see which services are up or down.

---

## Step 2: Restart a broken service via Portainer

1. Open [https://portainer.homelab.local](https://portainer.homelab.local)
2. Log in
3. Go to **Containers**
4. Find the service that's broken (e.g. `jellyfin`, `vaultwarden`)
5. Click **Restart**
6. Wait 30 seconds, then try the service again

---

## Step 3: Nothing works at all / dashboard is gone

The NAS (small box, always on) probably needs a restart:
1. Physically restart the NAS
2. Wait 3-5 minutes
3. Try the dashboard again: [https://home.homelab.local](https://home.homelab.local)

---

## Step 4: Still broken

Contact the maintainer. Take a photo of any error message visible on screen - it helps a lot.
