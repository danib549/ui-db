/* Minimal stdlib.h — declarations only */
#ifndef _STDLIB_H
#define _STDLIB_H

#include <stddef.h>

void *malloc(size_t size);
void *calloc(size_t nmemb, size_t size);
void *realloc(void *ptr, size_t size);
void  free(void *ptr);

int    atoi(const char *nptr);
long   atol(const char *nptr);
double atof(const char *nptr);

void   exit(int status);
void   abort(void);

#endif /* _STDLIB_H */
