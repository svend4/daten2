# Dockerfile for PHP + SQLite Flower Shop
FROM php:8.2-apache

# Install SQLite extension
RUN docker-php-ext-install pdo pdo_sqlite

# Enable Apache mod_rewrite
RUN a2enmod rewrite

# Set working directory
WORKDIR /var/www/html

# Copy application files
COPY . .

# Set permissions for SQLite database
RUN chmod 666 flowers.db && \
    chown -R www-data:www-data /var/www/html

# Expose port
EXPOSE 80

CMD ["apache2-foreground"]
