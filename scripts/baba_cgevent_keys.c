#include <ApplicationServices/ApplicationServices.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct {
  const char *name;
  CGKeyCode code;
} KeyMap;

static const KeyMap KEYS[] = {
    {"left", 123},   {"right", 124}, {"down", 125},  {"up", 126},
    {"undo", 6},     {"z", 6},       {"restart", 15}, {"space", 49},
    {"confirm", 49}, {"enter", 36},  {"escape", 53}, {"esc", 53},
};

static int lookup_key(const char *name, CGKeyCode *out) {
  for (size_t i = 0; i < sizeof(KEYS) / sizeof(KEYS[0]); i++) {
    if (strcmp(name, KEYS[i].name) == 0) {
      *out = KEYS[i].code;
      return 1;
    }
  }
  return 0;
}

static void send_key(CGKeyCode code, useconds_t hold_us) {
  CGEventRef down = CGEventCreateKeyboardEvent(NULL, code, true);
  CGEventRef up = CGEventCreateKeyboardEvent(NULL, code, false);
  if (down == NULL || up == NULL) {
    fprintf(stderr, "failed to create keyboard event\n");
    exit(2);
  }

  CGEventPost(kCGHIDEventTap, down);
  usleep(hold_us);
  CGEventPost(kCGHIDEventTap, up);

  CFRelease(down);
  CFRelease(up);
}

int main(int argc, char **argv) {
  useconds_t delay_us = 90000;
  useconds_t hold_us = 25000;

  int argi = 1;
  while (argi < argc && strncmp(argv[argi], "--", 2) == 0) {
    if (strcmp(argv[argi], "--delay-ms") == 0 && argi + 1 < argc) {
      delay_us = (useconds_t)(atoi(argv[argi + 1]) * 1000);
      argi += 2;
    } else if (strcmp(argv[argi], "--hold-ms") == 0 && argi + 1 < argc) {
      hold_us = (useconds_t)(atoi(argv[argi + 1]) * 1000);
      argi += 2;
    } else {
      fprintf(stderr, "unknown option: %s\n", argv[argi]);
      return 2;
    }
  }

  if (argi >= argc) {
    fprintf(stderr, "usage: %s [--delay-ms N] [--hold-ms N] move...\n", argv[0]);
    return 2;
  }

  for (; argi < argc; argi++) {
    CGKeyCode code;
    if (!lookup_key(argv[argi], &code)) {
      fprintf(stderr, "unknown key: %s\n", argv[argi]);
      return 2;
    }
    send_key(code, hold_us);
    usleep(delay_us);
  }

  return 0;
}
