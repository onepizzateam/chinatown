# chinatown

Mech Royale bot for the Builders Buildathon (protocol `mechfight/1`). Go, standard library only.

```sh
docker build --platform linux/amd64 -t bot .
```

For local testing, `MECH_P` and `MECH_SQ` (JSON objects of `Params` fields) override the base and
practice-mode parameters. Both are unset in the container, so the submitted bot runs the compiled defaults.
