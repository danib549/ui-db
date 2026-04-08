/* Minimal math.h — declarations only */
#ifndef _MATH_H
#define _MATH_H

double sin(double x);
double cos(double x);
double tan(double x);
double asin(double x);
double acos(double x);
double atan(double x);
double atan2(double y, double x);

double sinh(double x);
double cosh(double x);
double tanh(double x);

double exp(double x);
double log(double x);
double log10(double x);
double log2(double x);

double pow(double base, double exp);
double sqrt(double x);
double cbrt(double x);
double hypot(double x, double y);

double ceil(double x);
double floor(double x);
double round(double x);
double trunc(double x);
double fabs(double x);
double fmod(double x, double y);

double ldexp(double x, int exp);
double frexp(double x, int *exp);
double modf(double x, double *iptr);

#define HUGE_VAL  __builtin_huge_val()
#define INFINITY  __builtin_inff()
#define NAN       __builtin_nanf("")

#endif /* _MATH_H */
