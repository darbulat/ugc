# MAX services mini-app rollout

The MAX services button uses `MAX_REFERRAL_BOT_USERNAME` as the public username
of the bot that owns the MAX mini-app. Before rollout, compare this value to the
username returned by the authenticated MAX `GET /me` endpoint; do not log the
bot token. The bot's MAX mini-app must be configured to serve the intended app.

If the username or webhook base URL is empty, the services message is sent
without a launch button. Do not roll out this feature until both are configured.
The username is also used by MAX referral links, so changing it affects those
links and must be reviewed separately.

Deploy the app replicas serving the mini-app and the MAX bot together, without
changing feature flags. Verify the MAX launch and the services screen using an
authorized test account; a healthy container alone does not prove delivery or
navigation works.
