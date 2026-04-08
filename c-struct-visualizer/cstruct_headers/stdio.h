/* Minimal stdio.h — declarations only, enough for parsing */
#ifndef _STDIO_H
#define _STDIO_H

#include <stddef.h>

typedef struct _FILE FILE;

extern FILE *stdin;
extern FILE *stdout;
extern FILE *stderr;

typedef long fpos_t;

int    printf(const char *fmt, ...);
int    fprintf(FILE *stream, const char *fmt, ...);
int    sprintf(char *str, const char *fmt, ...);
int    snprintf(char *str, size_t size, const char *fmt, ...);

int    vprintf(const char *fmt, ...);
int    vfprintf(FILE *stream, const char *fmt, ...);
int    vsprintf(char *str, const char *fmt, ...);
int    vsnprintf(char *str, size_t size, const char *fmt, ...);

int    scanf(const char *fmt, ...);
int    fscanf(FILE *stream, const char *fmt, ...);
int    sscanf(const char *str, const char *fmt, ...);

int    fgetc(FILE *stream);
char  *fgets(char *s, int size, FILE *stream);
int    fputc(int c, FILE *stream);
int    fputs(const char *s, FILE *stream);
int    getc(FILE *stream);
int    getchar(void);
int    putc(int c, FILE *stream);
int    putchar(int c);
int    puts(const char *s);
int    ungetc(int c, FILE *stream);

FILE  *fopen(const char *path, const char *mode);
FILE  *freopen(const char *path, const char *mode, FILE *stream);
int    fclose(FILE *stream);
int    fflush(FILE *stream);

size_t fread(void *ptr, size_t size, size_t nmemb, FILE *stream);
size_t fwrite(const void *ptr, size_t size, size_t nmemb, FILE *stream);

int    fseek(FILE *stream, long offset, int whence);
long   ftell(FILE *stream);
void   rewind(FILE *stream);
int    fgetpos(FILE *stream, fpos_t *pos);
int    fsetpos(FILE *stream, const fpos_t *pos);

int    feof(FILE *stream);
int    ferror(FILE *stream);
void   clearerr(FILE *stream);
void   perror(const char *s);

int    remove(const char *path);
int    rename(const char *oldp, const char *newp);
FILE  *tmpfile(void);
char  *tmpnam(char *s);

void   setbuf(FILE *stream, char *buf);
int    setvbuf(FILE *stream, char *buf, int mode, size_t size);

#define EOF      (-1)
#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2
#define BUFSIZ   8192

#endif /* _STDIO_H */
